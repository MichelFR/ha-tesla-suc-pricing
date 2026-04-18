# Tesla Supercharger Pricing Integration

A custom component for Home Assistant to retrieve pricing and congestion data for a specific Tesla Supercharger location.

## Features
- **Pricing:** Fetches member and public pricing for Supercharger usage based on time-of-use (TOU) schedules.
- **Congestion:** Tracks real-time Supercharger occupancy percentages.
- **Auto-Update:** Automatically switches active rates according to Tesla's local time schedule, preventing unnecessary API calls. Retrieves updated schedules daily.
- **API Pooling:** Shared API session across all defined Superchargers, greatly minimizing API handshake times and bypassing `HTTP 429 Too Many Requests` bans.

## Installation

### HACS (Recommended)
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=MichelFR&repository=ha-tesla-suc-pricing&category=integration)

1. Open HACS in Home Assistant.
2. Add this repository as a custom repository (`Integration`).
3. Click "Download" and restart Home Assistant.

### Manual
1. Download the latest release `.zip`.
2. Extract the contents.
3. Move the `custom_components/tesla_suc_pricing` folder to your Home Assistant's `custom_components` directory.
4. Restart Home Assistant.

## Configuration
Go to **Settings** -> **Devices & Services** -> **Add Integration** and search for **Tesla Supercharger Pricing**.

Configuration now happens in two steps:

1. **Search nearby Superchargers**
   - `Latitude` and `Longitude` are pre-filled from your Home Assistant location.
   - `Country` is an ISO country code (for example `US`, `DE`, `FR`).
   - `Amount to find` controls how many nearby Superchargers are returned (max `10`).
2. **Select Supercharger**
   - Choose one of the returned nearby Superchargers from the dropdown.

> Note: Manual slug entry is no longer part of the setup flow.
