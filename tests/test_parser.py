"""Offline tests for api.py: CSV/HTML parsing, DST folds, tail trimming.

No dependencies, no network, no Home Assistant needed:

    python3 tests/test_parser.py
"""
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Stub aiohttp so api.py imports without the dependency.
aiohttp = types.ModuleType("aiohttp")
aiohttp.ClientSession = object
class _ClientError(Exception):
    pass
aiohttp.ClientError = _ClientError
aiohttp.ClientTimeout = lambda **kw: None
aiohttp.FormData = object
sys.modules["aiohttp"] = aiohttp

import dataclasses
_orig_dataclass = dataclasses.dataclass
def _dc_compat(*a, **kw):  # Python 3.9 lacks slots=True; HA runs 3.13
    kw.pop("slots", None)
    return _orig_dataclass(*a, **kw)
dataclasses.dataclass = _dc_compat

import importlib.util
pkg_dir = Path(__file__).resolve().parent.parent / "custom_components/ewrothrist"
pkg = types.ModuleType("ewrothrist")
pkg.__path__ = [str(pkg_dir)]
sys.modules["ewrothrist"] = pkg
for mod in ("const", "api"):
    spec = importlib.util.spec_from_file_location(f"ewrothrist.{mod}", pkg_dir / f"{mod}.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[f"ewrothrist.{mod}"] = m
    spec.loader.exec_module(m)
api = sys.modules["ewrothrist.api"]

ROW = ("<tr><td    data-title='Zeitstempel'>{ts}</td>"
       "<td  style='text-align:right'  data-color='#6E9ECF'  "
       "data-title='Verbrauch in kW'>{val}</td></tr>")


def build(rows):
    return "<tbody>" + "".join(ROW.format(ts=t, val=v) for t, v in rows) + "</tbody>"


client = api.EwrClient.__new__(api.EwrClient)
client._tz = ZoneInfo("Europe/Zurich")

# --- normal day ---------------------------------------------------------
html = build([("27.07.2026 00:00", "0.48"), ("27.07.2026 00:15", "0.49"),
              ("27.07.2026 00:30", "0.45"), ("27.07.2026 00:45", "-"),
              ("27.07.2026 01:00", "")])
slots = client._parse_table(html)
assert len(slots) == 5, len(slots)
assert slots[0].power_kw == 0.48
assert slots[3].power_kw == 0.0 and slots[4].power_kw == 0.0
assert slots[0].energy_kwh == 0.12
assert slots[0].start.isoformat() == "2026-07-27T00:00:00+02:00"
print("normal day OK")

# --- DST autumn: 26.10.2025 has the 02:00 block twice -------------------
rows = [("26.10.2025 01:45", "0.40")]
for rep in range(2):
    for mm in ("00", "15", "30", "45"):
        rows.append((f"26.10.2025 02:{mm}", "0.50"))
rows.append(("26.10.2025 03:00", "0.60"))
slots = client._parse_table(build(rows))
utc = [s.start.astimezone(ZoneInfo("UTC")).isoformat() for s in slots]
assert len(set(utc)) == len(utc), f"duplicate UTC timestamps: {utc}"
# first 02:00 = CEST (UTC 00:00), second 02:00 = CET (UTC 01:00)
assert utc[1] == "2025-10-26T00:00:00+00:00", utc[1]
assert utc[5] == "2025-10-26T01:00:00+00:00", utc[5]
# strictly increasing
prev = None
for u in utc:
    assert prev is None or u > prev, (prev, u)
    prev = u
print("DST autumn OK")

# --- DST spring: 29.03.2026, 02:00-02:45 does not exist -----------------
rows = [("29.03.2026 01:45", "0.40"), ("29.03.2026 03:00", "0.60")]
slots = client._parse_table(build(rows))
utc = [s.start.astimezone(ZoneInfo("UTC")).isoformat() for s in slots]
assert utc == ["2026-03-29T00:45:00+00:00", "2026-03-29T01:00:00+00:00"], utc
print("DST spring OK")

# --- tail trimming ------------------------------------------------------
tz = ZoneInfo("Europe/Zurich")
mk = lambda h, v: api.SlotValue(start=datetime(2026, 7, 28, h, tzinfo=tz), power_kw=v)
trimmed = api.trim_undelivered_tail([mk(0, 0.4), mk(1, 0.0), mk(2, 0.5), mk(3, 0.0), mk(4, 0.0)])
assert len(trimmed) == 3 and trimmed[-1].power_kw == 0.5
assert api.trim_undelivered_tail([mk(0, 0.0)]) == []
print("trim OK")

# --- hourly aggregation check (mirrors coordinator logic) ---------------
slots = [api.SlotValue(start=datetime(2026, 7, 28, 0, m, tzinfo=tz), power_kw=1.0)
         for m in (0, 15, 30, 45)]
total = sum(s.energy_kwh for s in slots)
assert total == 1.0, total
print("aggregation OK")

# --- CSV export path -----------------------------------------------------
CSV_HEAD = '"Zeitstempel";"Verbrauch in kW";\n'


def csv_of(rows):
    return CSV_HEAD + "".join(f'"{t}";"{v}";\n' for t, v in rows)


rows = [("27.07.2026 00:00", "0.48"), ("27.07.2026 00:15", "0.49"),
        ("27.07.2026 00:30", "0.45"), ("27.07.2026 00:45", "-"),
        ("27.07.2026 01:00", "")]
csv_slots = client._parse_csv(csv_of(rows))
html_slots = client._parse_table(build(rows))
assert len(csv_slots) == 5, len(csv_slots)
assert [s.power_kw for s in csv_slots] == [0.48, 0.49, 0.45, 0.0, 0.0]
# both paths must agree exactly
assert [(s.start, s.power_kw) for s in csv_slots] == \
       [(s.start, s.power_kw) for s in html_slots]
print("CSV path OK (identical to HTML path)")

# CSV must resolve DST folds the same way
rows = [("26.10.2025 01:45", "0.40")]
for _ in range(2):
    for mm in ("00", "15", "30", "45"):
        rows.append((f"26.10.2025 02:{mm}", "0.50"))
rows.append(("26.10.2025 03:00", "0.60"))
utc = [s.start.astimezone(ZoneInfo("UTC")).isoformat()
       for s in client._parse_csv(csv_of(rows))]
assert len(set(utc)) == len(utc), utc
assert utc[1] == "2025-10-26T00:00:00+00:00" and utc[5] == "2025-10-26T01:00:00+00:00"
print("CSV DST OK")

# a CSV without usable rows must yield nothing, so the caller falls back
assert client._parse_csv(CSV_HEAD) == []
assert client._parse_csv("<html>login</html>") == []
print("CSV empty/garbage OK")

# the export link must be found in real-world markup
import re as _re
link_html = ("<a class='csvExport' href='/de/formWork/csvTable.php?i=6a6879847ad42'>"
             "Als CSV exportieren</a>")
m = api._CSV_LINK_RE.search(link_html)
assert m and m.group(1) == "6a6879847ad42", m
print("CSV link regex OK")

# --- maintenance page detection -----------------------------------------
# Real shape: HTTP 200, logged-in sidebar present, no data.
maint = ("<html><body><a href='/de/services/logout.php'>Logout</a>"
         "<h1>Wartungsarbeiten</h1><p>Der gewuenschte Dienst steht momentan "
         "aufgrund von Wartungsarbeiten nicht zur Verfuegung.</p></body></html>")
assert "logout.php" in maint, "sanity: page must look logged in"
assert api._MAINTENANCE_RE.search(maint), "maintenance page must be detected"
assert not api._MAINTENANCE_RE.search(build([("27.07.2026 00:00", "0.48")]))
assert issubclass(api.EwrMaintenanceError, api.EwrConnectionError)
print("maintenance detection OK")

# --- fetch path (exercises _async_slots_from, not just the parsers) ------
# Regression guard: a NameError shipped here once, because the parsers were
# tested in isolation while nothing ever ran the code that fetches the CSV.
import asyncio


class _FakeResponse:
    def __init__(self, status, text):
        self.status, self._text = status, text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """Records requests and replays a canned response."""

    def __init__(self, status=200, text=""):
        self.status, self.text_body, self.calls = status, text, []

    def get(self, url, **kw):
        self.calls.append((url, kw.get("params")))
        if self.status == "boom":
            raise aiohttp.ClientError("connection reset")
        return _FakeResponse(self.status, self.text_body)


page = ("<a href='/de/formWork/csvTable.php?i=abc123'>Als CSV exportieren</a>"
        + build([("27.07.2026 00:00", "9.99")]))
real_csv = csv_of([("27.07.2026 00:00", "0.48"), ("27.07.2026 00:15", "0.49")])

# CSV available -> CSV wins over the (deliberately different) table values
client._session = _FakeSession(200, real_csv)
slots = asyncio.run(client._async_slots_from(page))
assert [s.power_kw for s in slots] == [0.48, 0.49], slots
assert client._session.calls[0][0].endswith("/de/formWork/csvTable.php"), \
    client._session.calls
assert client._session.calls[0][1] == {"i": "abc123"}, client._session.calls
print("fetch path uses CSV OK")

# CSV 500 -> falls back to the table
client._session = _FakeSession(500, "server error")
slots = asyncio.run(client._async_slots_from(page))
assert [s.power_kw for s in slots] == [9.99], slots
print("fetch path falls back on HTTP error OK")

# CSV connection error -> falls back to the table
client._session = _FakeSession("boom")
slots = asyncio.run(client._async_slots_from(page))
assert [s.power_kw for s in slots] == [9.99], slots
print("fetch path falls back on connection error OK")

# no CSV link at all -> table, and no request attempted
client._session = _FakeSession(200, real_csv)
slots = asyncio.run(client._async_slots_from(build([("27.07.2026 00:00", "1.23")])))
assert [s.power_kw for s in slots] == [1.23] and client._session.calls == []
print("fetch path without CSV link OK")

print("ALL PARSER TESTS PASSED")
