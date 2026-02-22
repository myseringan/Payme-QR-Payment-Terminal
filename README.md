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

A production-ready payment system for unattended vending machines and IoT devices in Uzbekistan. The ESP32 displays a Payme QR code, the customer scans and pays, and the device activates automatically.

**What it does:**

* Generates Payme checkout QR codes on an ESP32
* Processes payments through Payme's JSON-RPC API (CheckPerform → Create → Perform → Cancel)
* Notifies the ESP32 via MQTT in real time when payment is confirmed
* Manages product prices remotely through a REST API
* Handles full transaction lifecycle: creation, confirmation, cancellation, refunds

---

## System Architecture

```
┌──────────────────┐         ┌───────────────────┐         ┌──────────────┐
│   ESP32 Device   │  HTTPS  │   Flask Server     │  HTTP   │  Payme API   │
│                  │────────►│                    │◄───────►│              │
│ QR Display       │         │ /create-order      │         │ JSON-RPC     │
│ Output Control   │◄──MQTT──│ /payme (webhook)   │         │ Webhook      │
│                  │         │ /api/prices        │         │              │
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

1. **Customer** selects a product (button, touchscreen, or Serial command)
2. **ESP32** sends `POST /api/create-order` to the server
3. **Server** generates a Payme checkout URL and publishes it via MQTT
4. **ESP32** receives the MQTT message, displays the QR code
5. **Customer** scans QR with the Payme app and pays
6. **Payme** calls the server webhook: `CheckPerformTransaction` → `CreateTransaction` → `PerformTransaction`
7. **Server** publishes `{"status": "confirmed"}` via MQTT
8. **ESP32** receives confirmation, activates the output (relay, pump, LED, etc.)

---

## Tech Stack

| Layer | Technology | Description |
|-------|------------|-------------|
| Firmware | C++ / Arduino | ESP32 MQTT client, order management, output control |
| Server | Python / Flask | Payme webhook handler, REST API, MQTT publisher |
| Messaging | MQTT / HiveMQ | Real-time ESP32 ↔ Server communication |
| Payment | Payme JSON-RPC | Full transaction lifecycle (Uzbekistan market) |
| Storage | JSON files + NVS | Server transactions + ESP32 config cache |

---

## Project Structure

```
Payme-QR-Payment-Terminal/
├── firmware/
│   └── Payme_QR_ESP32.ino    # ESP32 sketch: MQTT, orders, output control
│
├── server/
│   └── app.py                # Flask server: Payme webhook + MQTT + REST API
│
├── screenshots/
└── README.md
```

---

## Firmware (ESP32)

**MQTT Communication** — Subscribes to `payments/{merchant_id}` and reacts to:
- `created` → QR URL ready to display
- `confirmed` → activates output pin (relay/pump/LED)
- `cancelled` → resets state

**Order Management** — Creates orders via HTTPS, auto-cancels after 3-minute timeout.

**Serial Commands** — Built-in test interface:
- `pay1` / `pay2` / `pay3` — create test orders
- `cancel` — cancel current order
- `status` — print current state

### Key Functions

| Function | Description |
|----------|-------------|
| `createOrder(productId, price)` | Sends order to server, triggers QR flow |
| `mqtt_callback()` | Handles payment status from MQTT |
| `activateOutput(amount)` | Turns on relay/LED on confirmed payment |
| `cancelOrder()` | Cancels pending order |
| `checkPaymentTimeout()` | Auto-cancel after 3 minutes |

---

## Server (Flask)

### Payme Webhook

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
| POST | `/api/create-order` | ESP32 creates order, gets QR URL back via MQTT |
| POST | `/api/cancel-order` | Cancel pending order |
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
const char* ssid        = "Your_WiFi";
const char* password    = "Your_Password";
const char* mqtt_server = "broker.hivemq.com";
const char* merchant_id = "your_merchant_id";
const char* server_url  = "https://your-server.com/api";
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

# Simulate full payment
curl -X POST http://localhost:3002/test-full-payment

# Or use Serial monitor: type "pay1" and press Enter
```

---

## Security Notes

- Payme authentication via Base64-encoded credentials (Basic Auth)
- `TEST_MODE` flag switches between test and production keys
- `DEBUG_ALLOW_ANY` bypasses auth (development only, never use in production)
- WiFi credentials and API keys should be stored in `.env`, not hardcoded

---

## Author

**Temur Eshmurodov** — [@myseringan](https://github.com/myseringan)

## License

MIT License — free to use and modify.
