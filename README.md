# Airzone for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Custom integration for [Airzone](https://www.airzone.es/) HVAC systems via local API.

## Installation via HACS

1. Open HACS in Home Assistant
2. Go to **Integrations**
3. Click the three dots menu → **Custom repositories**
4. Add this repository URL with category **Integration**
5. Search for **Airzone** and install it
6. Restart Home Assistant

## Configuration

Add the integration via **Settings → Devices & Services → Add Integration → Airzone**.

You will need:
- **Host**: IP address of your Airzone WebServer
- **Port**: API port (default: 3000)
- **System ID**: Airzone system ID (default: 1)

## Features

- Multi-zone climate control (modes, target temperature, fan speed)
- Temperature and humidity monitoring
- Energy consumption sensors
- Sleep timers (30/60/90 min)
- DHCP auto-discovery
- Polling interval: 60 seconds (HA default)
