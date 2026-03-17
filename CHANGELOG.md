# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.6] - 2026-03-17

### Fixed
- Added `services.yaml` for the `tesla_suc_pricing.refresh_cache` service registered by the integration.
- Declared the integration as config-entry-only with `CONFIG_SCHEMA` to satisfy Home Assistant validation for `async_setup`.
- Updated the Hassfest workflow to `actions/checkout@v5` to avoid the Node.js 20 deprecation warning on GitHub Actions.

## [1.2.5] - 2026-03-17

### Fixed
- Added integration-local brand assets under `custom_components/tesla_suc_pricing/brand/` so HACS validation can find `icon.png` and `logo.png` without relying on the fallback brands repository.

## [1.2.1] - 2024-03-16

### Fixed
- Improved Supercharger discovery logic to include sites marked with `"party"` location type (but containing supercharger data), ensuring all nearby stations are found.
- Fixed distance sorting to handle sites that might have missing root coordinates by falling back to `actual_latitude`/`actual_longitude` values.
- Resolved a cache mutation bug where distance calculations were incorrectly polluting the shared API cache.

## [1.2.0] - 2024-03-15

### Added
- Complete overhaul of config flow with geographic coordinate search. Enter latitude/longitude/radius to find nearby Superchargers.
- Dynamically fetch supercharger names based on location slug.
- Implemented Home Assistant `Store` caching for API endpoints (`get-locations` and `get-location-details`).
  - Automatically caches the massive `get-locations` (map) response for 14 Days.
  - Caches `get-location-details` (names) for 1 Day.
  - Data survives Home Assistant server restarts.
- Added a new `tesla_suc_pricing.refresh_cache` HA Service to clear memory manually.
- Integrated accurate distance calculation using the Haversine formula directly in `api.py`.
- New UI translations and configuration steps for coordinate-based searching.
- Added `brand/` directory with `icon.png` and `logo.png` for HACS UI integration.

### Fixed
- Correctly handle and surface HTTP 429 Rate Limit errors (and 403 Forbidden) during geographic searches so the UI shows an appropriate error message instead of failing out silently.

## [1.1.4] - Previous Release

### Changed
- Replaced the failing local JSON file approach with API-based lookups and direct API configuration.
- Combined past improvements and structured for optimal performance.
