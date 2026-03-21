"""Constants for the Tesla Supercharger Pricing integration."""
from datetime import timedelta

DOMAIN = "tesla_suc_pricing"

# Configuration
CONF_LOCATION_SLUG = "location_slug"
CONF_LOCALE = "locale"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_RADIUS_AMOUNT = "radius_amount"
CONF_COUNTRY = "country"

# Defaults
DEFAULT_LOCALE = "de_DE"
DEFAULT_COUNTRY = "DE"
DEFAULT_RADIUS_AMOUNT = 5
DEFAULT_SCAN_INTERVAL = timedelta(hours=1)
MIN_SCAN_INTERVAL = timedelta(minutes=15)
MAX_SCAN_INTERVAL = timedelta(hours=24)

# Scan interval options (in hours)
SCAN_INTERVAL_OPTIONS = {
    "15min": 0.25,
    "30min": 0.5,
    "1h": 1,
    "2h": 2,
    "4h": 4,
    "6h": 6,
    "12h": 12,
    "24h": 24,
}

# Known initial locations to provide in drop-down list
DEFAULT_LOCATIONS = [
    "29702",
    "302331",
    "400303",
    "426052",
    "BedburgSupercharger",
    "Frechendesupercharger",
    "erftstadtsupercharger",
    "vaterstettensupercharger",
]


# Storage / Cache
STORAGE_KEY_LOCATIONS = f"{DOMAIN}_locations_v2"
STORAGE_KEY_DETAILS = f"{DOMAIN}_details_v2"
STORAGE_KEY_PRICING = f"{DOMAIN}_pricing_v1"
STORAGE_VERSION = 2
CACHE_TTL_LOCATIONS = timedelta(days=14).total_seconds()
CACHE_TTL_DETAILS = timedelta(days=1).total_seconds()
CACHE_TTL_PRICING = timedelta(days=1).total_seconds()

# API
API_BASE_URL = "https://www.tesla.com"
API_ENDPOINT = "/api/findus/get-location-details"
TESLA_MAIN_URL = "https://www.tesla.com"
TESLA_FINDUS_URL = "https://www.tesla.com/findus"

# Sensor types
SENSOR_MEMBER_PRICE = "member_price"
SENSOR_PUBLIC_PRICE = "public_price"

# Vehicle types
VEHICLE_TYPE_TESLA = "TSLA"
VEHICLE_TYPE_NON_TESLA = "NTSLA"

# Fee types
FEE_TYPE_CHARGING = "CHARGING"
FEE_TYPE_CONGESTION = "CONGESTION"
