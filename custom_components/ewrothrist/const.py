"""Constants for the EW Rothrist Smart Meter integration."""

DOMAIN = "ewrothrist"

BASE_URL = "https://www.ewrothrist.ch"
LOGIN_URL = f"{BASE_URL}/de/services/login.php"
LASTGANG_URL = f"{BASE_URL}/de/services/lastgang.php"

CONF_BACKFILL_DAYS = "backfill_days"
CONF_SCAN_INTERVAL_MINUTES = "scan_interval_minutes"

DEFAULT_BACKFILL_DAYS = 365
DEFAULT_SCAN_INTERVAL_MINUTES = 60
MIN_SCAN_INTERVAL_MINUTES = 15

# Portal query parameters
TYPE_CONSUMPTION = "WirkBezug"
OBIS_CONSUMPTION = "1-1:1.5.0*255"

# One portal request may span at most this many days (15-min resolution kept).
MAX_DAYS_PER_REQUEST = 31

# Re-fetch this many hours before the newest imported statistic so that
# late-arriving corrections overwrite previously imported values.
OVERLAP_HOURS = 48

METER_TZ = "Europe/Zurich"
