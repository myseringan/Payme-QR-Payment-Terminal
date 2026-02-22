# Payme QR Payment Terminal

**IoT payment terminal for vending machines — ESP32 + Payme API + MQTT**

[![ESP32](https://img.shields.io/badge/ESP32-Firmware-green?style=flat-square&logo=espressif)](https://www.espressif.com/)
[![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)](https://python.org/)
[![Flask](https://img.shields.io/badge/Flask-Server-lightgrey?style=flat-square&logo=flask)](https://flask.palletsprojects.com/)
[![MQTT](https://img.shields.io/badge/MQTT-HiveMQ-purple?style=flat-square&logo=mqtt)](https://www.hivemq.com/)
[![Payme](https://img.shields.io/badge/Payme-Integration-00B2FF?style=flat-square)](https://payme.uz/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

---

## Overview

A production payment system for unattended vending machines in Uzbekistan. The customer selects a product on a touchscreen, a QR code appears, they scan it with the Payme app, and the machine dispenses the product automatically.

**Real-world deployment:** perfume vending machine ("Street Aroma") with 4 product slots, LVGL touchscreen UI, and remote price management.

**What it does:**

* Generates Payme checkout QR codes on an ESP32 touchscreen display
* Processes payments through Payme's JSON-RPC API (CheckPerform → Create → Perform → Cancel)
* Notifies the ESP32 via MQTT in real time when payment is confirmed
* Manages product prices remotely through a REST API
* Handles transaction lifecycle: creation, confirmation, cancellation, refunds

---

## System Architecture

```
┌──────────────────┐         ┌───────────────────┐         ┌──────────────┐
│   ESP32 Device   │  HTTPS  │   Flask Server     │  HTTP   │  Payme API   │
│                  │────────►│                    │◄───────►│              │
│ LVGL Touchscreen │         │ /create-order      │         │ JSON-RPC     │
│ QR Code Display  │◄──MQTT──│ /payme (webhook)   │         │ Webhook      │
│ Pump Control     │         │ /api/prices        │         │              │
└──────────────────┘         └────────┬───────────┘         └──────────────┘
                                      │
                                      │ MQTT (HiveMQ)
                                      │
                              ┌───────┴────────┐
                              │ payments/{id}   │
                              │                 │
                              │ • created       │
                              │ • confirmed     │
                              │ • cancelled     │
                              └────────────────┘
```

---

## Payment Flow

1. **Customer** selects a product on the ESP32 touchscreen
2. **ESP32** sends `POST /api/create-perfume-order` to the server
3. **Server** generates a Payme checkout URL and publishes it via MQTT
4. **ESP32** receives the MQTT message, renders a QR code on screen
5. **Customer** scans QR with the Payme app and pays
6. **Payme** calls the server webhook: `CheckPerformTransaction` → `CreateTransaction` → `PerformTransaction`
7. **Server** publishes `{"status": "confirmed"}` via MQTT
8. **ESP32** receives confirmation, activates the pump, dispenses product

---

## Tech Stack

| Layer | Technology | Description |
|-------|------------|-------------|
| Firmware | C++ / Arduino | ESP32 with LVGL UI, MQTT client, QR generation |
| Server | Python / Flask | Payme webhook handler, REST API, MQTT publisher |
| Messaging | MQTT / HiveMQ | Real-time ESP32 ↔ Server communication |
| Payment | Payme JSON-RPC | Full transaction lifecycle (Uzbekistan market) |
| Storage | JSON files + NVS | Server transactions + ESP32 price cache |

---

## Project Structure

```
Payme-QR-Payment-Terminal/
├── firmware/
│   ├── Payme_QR_ESP32.ino    # Main ESP32 sketch (simple MQTT listener)
│   └── payment.cpp           # Full implementation: QR gen, MQTT, orders, prices
│
├── server/
│   └── app.py                # Flask server: Payme webhook + MQTT + REST API
│
├── screenshots/
└── README.md
```

---

## Firmware (ESP32)

The firmware handles two main tasks:

**MQTT Communication** — Subscribes to `payments/{merchant_id}` and reacts to:
- `created` → generates QR code and displays it on screen
- `confirmed` → activates product dispensing
- `cancelled` → shows error screen and resets

**QR Code Generation** — Renders Payme checkout URLs directly on the LVGL display using RGB565 pixel buffer in PSRAM.

**Price Sync** — Periodically fetches current prices from the server via HTTPS and caches them in NVS (non-volatile storage).

### Key Functions

| Function | Description |
|----------|-------------|
| `createOrder(parfumId, price)` | Sends order request to server |
| `generateQrToImage(url)` | Renders QR code on LVGL display |
| `mqtt_callback()` | Handles payment status updates |
| `pollPrices()` | Syncs prices from server |
| `cancelOrder()` | Cancels pending order |

---

## Server (Flask)

### Payme Webhook Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/payme` | Payme JSON-RPC webhook (all transaction methods) |
| POST | `/payme-mqtt` | Alias for `/payme` |

Supported Payme methods:
- `CheckPerformTransaction` — validates amount and account
- `CreateTransaction` — creates new transaction (state: 1)
- `PerformTransaction` — confirms payment (state: 2), triggers MQTT
- `CancelTransaction` — cancels/refunds (state: -1/-2)
- `CheckTransaction` — returns transaction status
- `GetStatement` — returns transaction history for date range

### REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/create-perfume-order` | ESP32 creates order, gets QR URL |
| POST | `/api/cancel-perfume-order` | Cancel pending order |
| GET | `/api/prices` | Get product prices |
| POST | `/api/prices` | Update product prices (admin) |
| GET | `/api/orders` | List all orders |

### Debug Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Server health check |
| GET | `/mqtt-status` | MQTT connection status |
| POST | `/test-mqtt` | Send test MQTT message |
| POST | `/test-full-payment` | Simulate full payment |
| GET | `/debug-transactions` | View all transactions |

---

## Quick Start

### 1. Server Setup

```bash
pip install flask paho-mqtt python-dotenv

# Create .env file
cat > .env << EOF
MERCHANT_ID=your_merchant_id
PAYME_KEY=your_secret_key
PAYME_TEST_KEY=your_test_key
MQTT_BROKER=broker.hivemq.com
TEST_MODE=true
EOF

python app.py
# Server starts on http://0.0.0.0:3002
```

### 2. Flash ESP32

Update WiFi and MQTT settings in the firmware:
```cpp
const char* ssid = "Your_WiFi";
const char* password = "Your_Password";
const char* mqtt_server = "broker.hivemq.com";
const char* mqtt_topic = "payments/your_merchant_id";
```

Flash with Arduino IDE or PlatformIO.

### 3. Configure Payme

In the Payme merchant dashboard, set the webhook URL:
```
https://your-server.com/payme
```

### 4. Test

```bash
# Test MQTT connection
curl -X POST http://localhost:3002/test-mqtt

# Simulate payment
curl -X POST http://localhost:3002/test-full-payment

# Create order (as ESP32 would)
curl -X POST http://localhost:3002/api/create-perfume-order \
  -H "Content-Type: application/json" \
  -d '{"device_id": "esp32-01", "parfum_id": 1, "amount": 5000}'
```

---

## Security Notes

- Payme authentication via Base64-encoded credentials (Basic Auth)
- `TEST_MODE` flag switches between test and production keys
- `DEBUG_ALLOW_ANY` bypasses auth (development only, never use in production)
- WiFi credentials and API keys should be stored in `.env` / `pre.h`, not hardcoded

---

## Author

**Temur Eshmurodov** — [@myseringan](https://github.com/myseringan)

## License

MIT License — free to use and modify.
