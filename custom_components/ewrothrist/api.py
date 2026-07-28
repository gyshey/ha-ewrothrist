"""Client for the EW Rothrist customer portal (Weblication CMS).

The portal has no JSON API: after a multipart form login the load-profile
page (lastgang.php) renders the 15-minute values server-side as an HTML
table.  This client logs in, requests arbitrary date ranges
(zeitraum=datum) and parses the table rows.

Quirks discovered by inspection (2026-07):
- Login: POST multipart email/passwort/leerLassen(honeypot, empty)/
  loginFormSent=1; success iff the response contains "logout.php".
- Unauthenticated requests to lastgang.php redirect (302) to login.php.
- Values are average power in kW per 15-minute slot; slots that have not
  been delivered yet are rendered as 0.00 (indistinguishable from a true
  zero, callers must trim the trailing zero run).
- Date range requests up to 31 days keep the 15-minute resolution.
- The page carries a CSV export link; that export is preferred over the
  table markup (see _async_slots_from).
- A maintenance page is served as a normal 200 with the logged-in sidebar,
  so it has to be detected explicitly.
- Timestamps are real local wall-clock times, confirmed at both DST
  switches (verified 2026-07 against the live portal):
    * spring 29.03.2026, a 23-hour day -> 92 slots, 02:00-02:45 correctly
      absent (01:45 is followed by 03:00);
    * autumn 26.10.2025, a 25-hour day -> 96 slots, the repeated
      02:00-02:45 block is *not* reported.
  So the mapping to Europe/Zurich is sound, and once a year one hour is
  simply missing from the portal's own data. The fold handling below stays
  in place in case a meter ever does report the repeat.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import aiohttp

from .const import (
    CSV_URL,
    LASTGANG_URL,
    LOGIN_URL,
    MAX_DAYS_PER_REQUEST,
    METER_TZ,
    OBIS_CONSUMPTION,
    TYPE_CONSUMPTION,
)

_LOGGER = logging.getLogger(__name__)

_ROW_RE = re.compile(
    r"data-title='Zeitstempel'>\s*"
    r"(\d{2})\.(\d{2})\.(\d{4}) (\d{2}):(\d{2})\s*</td>"
    r"\s*<td[^>]*>\s*([0-9.,-]*)\s*<",
)
_METER_RE = re.compile(
    r"<select[^>]*id='zaehler'.*?</select>", re.DOTALL
)
_OPTION_RE = re.compile(r"<option[^>]*value='([^']+)'")
# The rendered page offers "Als CSV exportieren"; the id is a per-render
# uniqid() the server maps back to the table it just built for this session.
_CSV_LINK_RE = re.compile(r"csvTable\.php\?i=([A-Za-z0-9]+)")
# Observed 2026-07: the portal answers with a 200 "Wartungsarbeiten" page
# (services/error.php) that still renders the logged-in sidebar.
_MAINTENANCE_RE = re.compile(r"Wartungsarbeiten", re.I)
_CSV_ROW_RE = re.compile(
    r'^"(\d{2})\.(\d{2})\.(\d{4}) (\d{2}):(\d{2})";"([0-9.,-]*)"'
)


class EwrAuthError(Exception):
    """Login failed (wrong credentials or changed login form)."""


class EwrConnectionError(Exception):
    """Portal not reachable or returned an unexpected response."""


class EwrMaintenanceError(EwrConnectionError):
    """Portal served its maintenance page instead of the data."""


@dataclass(slots=True)
class SlotValue:
    """One 15-minute load profile slot."""

    start: datetime  # timezone-aware (Europe/Zurich, folds resolved)
    power_kw: float

    @property
    def energy_kwh(self) -> float:
        return self.power_kw * 0.25


def trim_undelivered_tail(slots: list["SlotValue"]) -> list["SlotValue"]:
    """Drop the trailing run of 0.00 slots (not yet delivered by the DSO)."""
    last_nonzero = -1
    for i, slot in enumerate(slots):
        if slot.power_kw > 0:
            last_nonzero = i
    if last_nonzero < 0:
        return []
    return slots[: last_nonzero + 1]


class EwrClient:
    """Session-holding client for the EW Rothrist portal."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._tz = ZoneInfo(METER_TZ)

    async def async_login(self) -> None:
        """Log in and keep the session cookie in the client session."""
        form = aiohttp.FormData()
        form.add_field("email", self._email)
        form.add_field("passwort", self._password)
        form.add_field("leerLassen", "")  # honeypot, must stay empty
        form.add_field("loginFormSent", "1")
        try:
            async with self._session.post(LOGIN_URL, data=form, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                text = await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise EwrConnectionError(f"Login request failed: {err}") from err
        if "logout.php" not in text:
            raise EwrAuthError("Portal rejected the credentials")
        _LOGGER.debug("Logged in to EW Rothrist portal as %s", self._email)

    async def _async_get_lastgang(self, params: dict[str, str]) -> str:
        """GET lastgang.php, re-logging in once if the session expired."""
        for attempt in (1, 2):
            try:
                async with self._session.get(
                    LASTGANG_URL, params=params, timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    text = await resp.text()
                    final_url = str(resp.url)
            except (aiohttp.ClientError, TimeoutError) as err:
                raise EwrConnectionError(f"Portal request failed: {err}") from err
            if "login.php" not in final_url and "logout.php" in text:
                # The maintenance page is a normal 200 and still carries the
                # logged-in sidebar, so it passes the session check above.
                # Treat it as "portal down", not as "no consumption".
                if "error.php" in final_url or _MAINTENANCE_RE.search(text):
                    raise EwrMaintenanceError(
                        "Portal is in maintenance; consumption data unavailable"
                    )
                return text
            if attempt == 1:
                _LOGGER.debug("Session expired, logging in again")
                await self.async_login()
        raise EwrConnectionError("Still redirected to login after re-authentication")

    async def async_get_meters(self) -> list[str]:
        """Return the meter ids selectable in the portal."""
        today = date.today().strftime("%d.%m.%Y")
        html = await self._async_get_lastgang(
            {"zeitraum": "datum", "datum_von": today, "datum_bis": today}
        )
        sel = _METER_RE.search(html)
        if not sel:
            raise EwrConnectionError("Meter dropdown not found on portal page")
        meters = _OPTION_RE.findall(sel.group(0))
        if not meters:
            raise EwrConnectionError("No meters listed in portal dropdown")
        return meters

    async def async_fetch_range(
        self, meter: str, start: date, end: date
    ) -> list[SlotValue]:
        """Fetch consumption slots for [start, end] (inclusive, local dates).

        Splits into portal-sized chunks automatically and returns the slots
        sorted by time.  Trailing not-yet-delivered slots are included as
        0.0 - callers trim them.
        """
        slots: list[SlotValue] = []
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(chunk_start + timedelta(days=MAX_DAYS_PER_REQUEST - 1), end)
            params = {
                "zaehler": meter,
                "type": TYPE_CONSUMPTION,
                "obiscode": OBIS_CONSUMPTION,
                "zeitraum": "datum",
                "datum_von": chunk_start.strftime("%d.%m.%Y"),
                "datum_bis": chunk_end.strftime("%d.%m.%Y"),
            }
            html = await self._async_get_lastgang(params)
            chunk = await self._async_slots_from(html)
            _LOGGER.debug(
                "Fetched %s slots for %s..%s", len(chunk), chunk_start, chunk_end
            )
            slots.extend(chunk)
            chunk_start = chunk_end + timedelta(days=1)
        slots.sort(key=lambda s: s.start)
        return slots

    async def _async_slots_from(self, html: str) -> list[SlotValue]:
        """Prefer the portal's own CSV export, fall back to the HTML table.

        The rendered page carries an "Als CSV exportieren" link whose id the
        server maps back to the table it just built. That export is a stable,
        machine-readable contract; scraping the table markup is the fallback
        for the case where the link is missing or the download fails.
        """
        match = _CSV_LINK_RE.search(html)
        if match:
            try:
                async with self._session.get(
                    CSV_URL,
                    params={"i": match.group(1)},
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status == 200:
                        slots = self._parse_csv(await resp.text())
                        if slots:
                            return slots
                    _LOGGER.debug("CSV export returned status %s", resp.status)
            except (aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug("CSV export failed (%s), parsing HTML instead", err)
        else:
            _LOGGER.debug("No CSV export link on page, parsing HTML instead")
        return self._parse_table(html)

    def _parse_csv(self, csv_text: str) -> list[SlotValue]:
        """Parse the portal's CSV export (semicolon separated, quoted)."""
        rows = []
        for line in csv_text.splitlines():
            m = _CSV_ROW_RE.match(line.strip())
            if m:
                rows.append(m.groups())
        return self._to_slots(rows)

    def _parse_table(self, html: str) -> list[SlotValue]:
        """Parse the server-rendered table into slot values."""
        return self._to_slots(m.groups() for m in _ROW_RE.finditer(html))

    def _to_slots(self, rows) -> list[SlotValue]:
        """Turn (dd, mm, yyyy, HH, MM, value) tuples into slot values."""
        slots: list[SlotValue] = []
        seen: set[datetime] = set()
        for day, month, year, hour, minute, raw in rows:
            raw = raw.replace(",", ".").strip()
            try:
                value = float(raw) if raw not in ("", "-") else 0.0
            except ValueError:
                continue
            naive = datetime(int(year), int(month), int(day), int(hour), int(minute))
            # DST end (autumn): the 02:00-02:45 slots appear twice; the
            # second occurrence is the post-transition (fold=1) hour.
            fold = 1 if naive in seen else 0
            seen.add(naive)
            slots.append(
                SlotValue(start=naive.replace(tzinfo=self._tz, fold=fold), power_kw=value)
            )
        return slots
