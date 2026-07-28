"""Coordinator: polls the portal and feeds long-term statistics.

The portal delivers 15-minute average power with a lag of a few hours
(new batches appear several times a day).  Because the data arrives late,
regular sensor states cannot represent it - instead the coordinator
imports the values as external long-term statistics
(``ewrothrist:<meter>_energy``), which the Energy dashboard picks up
retroactively at full hourly resolution.

Import strategy per refresh:
- window = [newest imported statistic - OVERLAP_HOURS, today], first run
  uses the configured backfill.
- trailing 0.00 slots are "not delivered yet" and get trimmed (a real
  all-zero tail is corrected on a later refresh once newer data exists).
- hourly kWh buckets are rebuilt over the whole window and upserted; the
  cumulative sum continues from the last statistic before the window.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    EwrAuthError,
    EwrClient,
    EwrConnectionError,
    SlotValue,
    trim_undelivered_tail,
)
from .const import (
    CONF_BACKFILL_DAYS,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_BACKFILL_DAYS,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    OVERLAP_HOURS,
)

_LOGGER = logging.getLogger(__name__)

try:  # HA >= 2025.4: has_mean replaced by mean_type
    from homeassistant.components.recorder.models import StatisticMeanType

    _MEAN_NONE_KWARGS: dict[str, Any] = {"mean_type": StatisticMeanType.NONE}
except ImportError:  # pragma: no cover - older cores
    _MEAN_NONE_KWARGS = {"has_mean": False}


@dataclass(slots=True)
class EwrData:
    """State exposed to the sensor platform."""

    last_slot_time: datetime | None
    last_slot_kw: float | None
    energy_today_kwh: float | None
    energy_yesterday_kwh: float | None
    statistic_id: str


class EwrCoordinator(DataUpdateCoordinator[EwrData]):
    """Fetch portal data and maintain external statistics."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: EwrClient,
        meter: str,
    ) -> None:
        minutes = entry.options.get(
            CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {meter}",
            update_interval=timedelta(minutes=minutes),
        )
        self.client = client
        self.meter = meter
        self.statistic_id = f"{DOMAIN}:{meter.lower()}_energy"

    async def _async_update_data(self) -> EwrData:
        try:
            return await self._update()
        except EwrAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EwrConnectionError as err:
            raise UpdateFailed(str(err)) from err

    async def _update(self) -> EwrData:
        today = dt_util.now().date()
        last_stat_end = await self._newest_statistic_end()
        if last_stat_end is None:
            backfill = self.config_entry.options.get(
                CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS
            )
            window_start_date = today - timedelta(days=backfill)
            _LOGGER.info(
                "First import for %s: backfilling %s days", self.meter, backfill
            )
        else:
            overlap_start = last_stat_end - timedelta(hours=OVERLAP_HOURS)
            window_start_date = dt_util.as_local(overlap_start).date()

        slots = await self.client.async_fetch_range(
            self.meter, window_start_date, today
        )
        slots = trim_undelivered_tail(slots)
        if slots:
            await self._import_statistics(slots)
        return self._build_sensor_data(slots)

    async def _newest_statistic_end(self) -> datetime | None:
        """Return the end of the newest imported statistic hour, if any."""
        stats = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics,
            self.hass,
            1,
            self.statistic_id,
            False,
            {"sum"},
        )
        rows = stats.get(self.statistic_id)
        if not rows:
            return None
        return dt_util.utc_from_timestamp(rows[-1]["start"]) + timedelta(hours=1)

    async def _sum_before(self, window_start: datetime) -> float:
        """Cumulative sum of the last statistic strictly before window_start."""

        async def query(start: datetime) -> list | None:
            stats = await get_instance(self.hass).async_add_executor_job(
                statistics_during_period,
                self.hass,
                start,
                window_start,
                {self.statistic_id},
                "hour",
                None,
                {"sum"},
            )
            return stats.get(self.statistic_id)

        # The window normally starts just inside existing statistics, so a
        # short lookback suffices; fall back to the full history for gaps.
        rows = await query(window_start - timedelta(days=7))
        if not rows:
            rows = await query(window_start - timedelta(days=3660))
        if not rows:
            return 0.0
        return rows[-1]["sum"] or 0.0

    async def _import_statistics(self, slots: list[SlotValue]) -> None:
        hourly: dict[datetime, float] = {}
        for slot in slots:
            hour_start = dt_util.as_utc(slot.start).replace(minute=0, second=0)
            hourly[hour_start] = hourly.get(hour_start, 0.0) + slot.energy_kwh

        if not hourly:
            return
        window_start = min(hourly)
        running_sum = await self._sum_before(window_start)

        statistics: list[StatisticData] = []
        for hour_start in sorted(hourly):
            running_sum += hourly[hour_start]
            statistics.append(
                StatisticData(start=hour_start, sum=round(running_sum, 4))
            )

        metadata = StatisticMetaData(
            statistic_id=self.statistic_id,
            source=DOMAIN,
            name=f"EW Rothrist Verbrauch {self.meter}",
            unit_of_measurement="kWh",
            has_sum=True,
            **_MEAN_NONE_KWARGS,
        )
        async_add_external_statistics(self.hass, metadata, statistics)
        _LOGGER.debug(
            "Imported %s hourly statistics (%s .. %s)",
            len(statistics),
            min(hourly),
            max(hourly),
        )

    def _build_sensor_data(self, slots: list[SlotValue]) -> EwrData:
        last = next(
            (s for s in reversed(slots) if s.power_kw > 0), slots[-1] if slots else None
        )
        today = dt_util.now().date()

        def day_total(day: date) -> float | None:
            day_slots = [s for s in slots if s.start.date() == day]
            if not day_slots:
                return None
            return round(sum(s.energy_kwh for s in day_slots), 3)

        return EwrData(
            last_slot_time=last.start if last else None,
            last_slot_kw=last.power_kw if last else None,
            energy_today_kwh=day_total(today),
            energy_yesterday_kwh=day_total(today - timedelta(days=1)),
            statistic_id=self.statistic_id,
        )
