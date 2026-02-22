from flask import Flask, request, jsonify
import base64
import time
import json
import os
import paho.mqtt.client as mqtt
from functools import wraps
from datetime import datetime
from threading import Lock
import random
import string
from dotenv import load_dotenv

# Загрузка .env
load_dotenv()

app = Flask(__name__)

# ============ КОНФИГУРАЦИЯ ============
# Payme credentials
MERCHANT_ID = os.getenv("MERCHANT_ID", "")
SECRET_KEY = os.getenv("PAYME_KEY", "")
TEST_KEY = os.getenv("PAYME_TEST_KEY", "")

# MQTT настройки (как в твоём Node.js)
MQTT_BROKER = os.getenv("MQTT_BROKER", "broker.hivemq.com")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_PROTOCOL = os.getenv("MQTT_PROTOCOL", "mqtt")

# Режим тестирования
TEST_MODE = os.getenv("TEST_MODE", "true").lower() == "true"
DEBUG_ALLOW_ANY = os.getenv("DEBUG_ALLOW_ANY", "0") == "1"

# Файл для хранения транзакций
PROCESSED_FILE = os.getenv("PROCESSED_FILE", "processed.json")

# Минимальная сумма в сумах
MIN_AMOUNT_UZS = 100

# ============ ХРАНИЛИЩЕ ТРАНЗАКЦИЙ ============
transactions_lock = Lock()

def load_transactions():
    """Загрузка транзакций из файла"""
    try:
        if os.path.exists(PROCESSED_FILE):
            with open(PROCESSED_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"⚠️ Ошибка загрузки транзакций: {e}")
    return {}

def save_transactions(data):
    """Сохранение транзакций в файл"""
    try:
        with open(PROCESSED_FILE, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Ошибка сохранения транзакций: {e}")

# ============ MQTT SETUP (как в твоём Node.js) ============
client_id = 'payme-server-' + ''.join(random.choices(string.hexdigits[:16], k=8))
mqtt_url = f"{MQTT_PROTOCOL}://{MQTT_BROKER}"

print(f"🔗 Connecting to MQTT: {mqtt_url}")

mqtt_client = mqtt.Client(client_id=client_id)
mqtt_connected = False

def on_connect(client, userdata, flags, rc):
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        print(f"✅ MQTT connected to {mqtt_url}")
        print(f"📡 MQTT topics:", {
            "payments": f"payments/{MERCHANT_ID}",
            "control": f"control/{MERCHANT_ID}",
            "config": f"config/{MERCHANT_ID}"
        })
    else:
        mqtt_connected = False
        print(f"❌ MQTT connection failed with code {rc}")

def on_disconnect(client, userdata, rc):
    global mqtt_connected
    mqtt_connected = False
    print("🔒 MQTT connection closed")

def on_message(client, userdata, msg):
    print(f"📨 MQTT message received: {msg.topic} -> {msg.payload.decode()}")

mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.on_message = on_message

# Подключение к MQTT
try:
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.loop_start()
except Exception as e:
    print(f"❌ MQTT initial connection error: {e}")

# ============ MQTT PUBLISH (как в твоём Node.js) ============
def publish_mqtt(topic, payload, context="unknown"):
    """Отправка сообщения через MQTT (логика из твоего Node.js)"""
    print(f"\n📡 MQTT [{context}]: Attempting to publish to {topic}")
    print(f"📡 MQTT [{context}]: Payload:", payload)
    print(f"📡 MQTT [{context}]: Connected: {mqtt_connected}")

    if not mqtt_connected:
        print(f"❌ MQTT [{context}]: Not connected, cannot publish to {topic}")
        return False

    message = json.dumps(payload, ensure_ascii=False)

    result = mqtt_client.publish(topic, message, qos=1)

    if result.rc == 0:
        print(f"✅ MQTT [{context}]: Successfully published to {topic}")
        print(f"✅ MQTT [{context}]: Message: {message}")
        return True
    else:
        print(f"❌ MQTT [{context}]: Publish error to {topic}: rc={result.rc}")
        return False

# ============ JSON-RPC HELPERS ============
def jsonrpc_success(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}

def jsonrpc_error(req_id, code, message, data=None):
    error = {"code": code, "message": message}
    if data:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": error}

# ============ КОДЫ ОШИБОК PAYME ============
class PaymeError:
    INVALID_AMOUNT = -31001
    INVALID_ACCOUNT = -31050
    ACCOUNT_PENDING = -31051
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    TRANSACTION_NOT_FOUND = -31003
    CANT_PERFORM = -31008
    CANT_CANCEL = -31007
    UNAUTHORIZED = -32504
    SYSTEM_ERROR = -32400

# ============ AUTH MIDDLEWARE (как в твоём Node.js) ============
def check_auth(f):
    """Проверка авторизации от Payme (логика из твоего Node.js)"""
    @wraps(f)
    def decorated(*args, **kwargs):
        raw_headers = request.headers
        candidate = (
            raw_headers.get('X-Auth') or
            raw_headers.get('X-Payme-Auth') or
            raw_headers.get('Authorization') or
            ""
        )

        print("===== AUTH DEBUG =====")
        print(f"Raw authorization header: {candidate[:50]}..." if len(candidate) > 50 else f"Raw authorization header: {candidate}")

        # Handle Basic Auth (Payme format)
        if candidate.lower().startswith("basic "):
            try:
                base64_credentials = candidate[6:]
                credentials = base64.b64decode(base64_credentials).decode('utf-8')
                print(f"Decoded Basic Auth: {credentials[:20]}..." if len(credentials) > 20 else f"Decoded Basic Auth: {credentials}")

                parts = credentials.split(':')
                if len(parts) >= 2:
                    candidate = parts[1]
                    print(f"Extracted password/key: {candidate[:10]}..." if candidate else "empty")
            except Exception as e:
                print(f"Failed to decode Basic Auth: {e}")
                candidate = ""
        # Handle Bearer token
        elif candidate.lower().startswith("bearer "):
            candidate = candidate[7:]

        candidate = candidate.strip()

        # Query param fallback for debug
        if not candidate and request.args.get('key'):
            candidate = request.args.get('key', '').strip()

        # Debug bypass
        if DEBUG_ALLOW_ANY:
            print("DEBUG_ALLOW_ANY=1 — авторизация пропущена (temporary).")
            return f(*args, **kwargs)

        # Get expected key
        expected_key = TEST_KEY if TEST_MODE else SECRET_KEY

        # Extract key from "Payme:KEY" format if needed
        if ':' in expected_key:
            expected_key = expected_key.split(':')[1]

        print(f"Final candidate token: {candidate[:20]}..." if len(candidate) > 20 else f"Final candidate token: {candidate}")
        print(f"Expected key: {expected_key[:20]}..." if len(expected_key) > 20 else f"Expected key: {expected_key}")

        if not candidate or candidate != expected_key:
            print("❌ Auth failed: token mismatch or missing.")
            return jsonify(jsonrpc_error(
                request.json.get('id') if request.json else None,
                PaymeError.UNAUTHORIZED,
                "Insufficient privileges",
                {"ru": "Недостаточно привилегий", "uz": "Yetarli imtiyozlar yo'q"}
            ))

        print("✅ Auth successful!")
        return f(*args, **kwargs)
    return decorated

# ============ MAIN PAYME ENDPOINT ============
@app.route('/payme-mqtt', methods=['POST'])
@app.route('/payme', methods=['POST'])
@check_auth
def payme_webhook():
    """Главный endpoint для Payme webhook (логика из твоего Node.js)"""

    body = request.json or {}
    req_id = body.get('id')
    method = body.get('method')
    params = body.get('params', {})

    print(f"\n▶️ Payme API call: {method} (ID: {req_id})")

    if not method:
        return jsonify(jsonrpc_error(req_id, -32600, "Invalid request (no method)"))

    if not params or not isinstance(params, dict):
        return jsonify(jsonrpc_error(req_id, PaymeError.INVALID_PARAMS, "Invalid params"))

    # Get transaction id and amount
    transaction_id = params.get('id') or params.get('transaction')
    if not transaction_id and params.get('payment'):
        transaction_id = params['payment'].get('id')

    amount_tiyin = params.get('amount')
    if amount_tiyin is None and params.get('payment'):
        amount_tiyin = params['payment'].get('amount')

    try:
        amount_tiyin = int(amount_tiyin) if amount_tiyin is not None else None
    except:
        amount_tiyin = None

    try:
        with transactions_lock:
            processed = load_transactions()

            # === CheckPerformTransaction ===
            if method == 'CheckPerformTransaction':
                if amount_tiyin is None:
                    return jsonify(jsonrpc_error(req_id, PaymeError.INVALID_PARAMS, "Missing amount"))

                amount_sum = amount_tiyin / 100
                print(f"🔍 CheckPerformTransaction: amount={amount_sum} UZS ({amount_tiyin} tiyin), account={params.get('account')}")

                if amount_sum < MIN_AMOUNT_UZS:
                    return jsonify(jsonrpc_error(req_id, PaymeError.INVALID_AMOUNT, f"Minimum amount is {MIN_AMOUNT_UZS} UZS."))

                # Валидация account
                if not params.get('account') or not isinstance(params.get('account'), dict):
                    return jsonify(jsonrpc_error(req_id, PaymeError.INVALID_ACCOUNT, "Invalid account parameters"))

                # Items для чека
                items = [{
                    "title": "Оплата товаров/услуг",
                    "price": amount_tiyin,
                    "count": 1,
                    "code": "007",
                    "package_code": "12345678901234",
                    "vat_percent": 15
                }]

                return jsonify(jsonrpc_success(req_id, {
                    "allow": True,
                    "detail": {
                        "receipt_type": 0,
                        "items": items
                    }
                }))

            # === CreateTransaction ===
            elif method == 'CreateTransaction':
                if not transaction_id or amount_tiyin is None:
                    return jsonify(jsonrpc_error(req_id, PaymeError.INVALID_PARAMS, "Missing transaction id or amount"))

                amount_sum = amount_tiyin / 100

                if amount_sum < MIN_AMOUNT_UZS:
                    return jsonify(jsonrpc_error(req_id, PaymeError.INVALID_AMOUNT, f"Invalid amount: minimum is {MIN_AMOUNT_UZS} UZS"))

                # Если транзакция с таким ID уже существует - вернуть её данные (идемпотентность)
                if transaction_id in processed:
                    tr = processed[transaction_id]
                    return jsonify(jsonrpc_success(req_id, {
                        "create_time": tr['create_time'],
                        "transaction": transaction_id,
                        "state": tr['state']
                    }))

                account = params.get('account', {})

                # Проверка: есть ли pending транзакция для этого аккаунта (ДРУГАЯ транзакция)
                for tid, tx in processed.items():
                    if tx.get('state') == 1 and tx.get('account') == account:
                        # Уже есть ожидающая транзакция для этого аккаунта
                        return jsonify(jsonrpc_error(req_id, PaymeError.ACCOUNT_PENDING, "Account has pending transaction"))

                # Создаём новую транзакцию
                create_time = int(time.time() * 1000)
                processed[transaction_id] = {
                    "status": "created",
                    "state": 1,
                    "amount": amount_sum,
                    "amount_tiyin": amount_tiyin,
                    "create_time": create_time,
                    "account": account,
                    "payme_raw": params
                }
                save_transactions(processed)

                # MQTT publish
                topic = f"payments/{MERCHANT_ID}"
                payload = {
                    "status": "created",
                    "transaction_id": transaction_id,
                    "amount": amount_sum,
                    "amount_tiyin": amount_tiyin,
                    "account": account,
                    "time": create_time
                }
                publish_mqtt(topic, payload, "CreateTransaction")

                return jsonify(jsonrpc_success(req_id, {
                    "create_time": create_time,
                    "transaction": transaction_id,
                    "state": 1
                }))

            # === PerformTransaction ===
            elif method == 'PerformTransaction':
                if not transaction_id:
                    return jsonify(jsonrpc_error(req_id, PaymeError.INVALID_PARAMS, "Missing transaction id"))

                if transaction_id not in processed:
                    return jsonify(jsonrpc_error(req_id, PaymeError.TRANSACTION_NOT_FOUND, "Transaction not found."))

                record = processed[transaction_id]

                if record.get('state') == 2:
                    # Уже выполнена
                    return jsonify(jsonrpc_success(req_id, {
                        "perform_time": record['perform_time'],
                        "transaction": transaction_id,
                        "state": 2,
                        "receivers": None
                    }))

                if record.get('state') != 1:
                    return jsonify(jsonrpc_error(req_id, PaymeError.CANT_PERFORM, "Cannot perform transaction in current state."))

                # Выполняем транзакцию
                perform_time = int(time.time() * 1000)
                record['status'] = "performed"
                record['perform_time'] = perform_time
                record['state'] = 2
                processed[transaction_id] = record
                save_transactions(processed)

                print(f"""
╔══════════════════════════════════════════════════════╗
║           💰 ОПЛАТА УСПЕШНО ПРОШЛА! 💰              ║
╠══════════════════════════════════════════════════════╣
║  Сумма: {record['amount']:,.0f} сум
║  ID транзакции: {transaction_id}
║  Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
╚══════════════════════════════════════════════════════╝
""")

                # >>> MQTT - АКТИВАЦИЯ АВТОМАТА <<<
                topic = f"payments/{MERCHANT_ID}"
                payload = {
                    "status": "confirmed",
                    "amount": record['amount'],
                    "amount_tiyin": record['amount_tiyin'],
                    "currency": "UZS",
                    "transaction_id": transaction_id,
                    "account": record.get('account', {}),
                    "time": perform_time
                }
                publish_mqtt(topic, payload, "PerformTransaction")

                print(f"✅ Transaction performed: {transaction_id}")

                return jsonify(jsonrpc_success(req_id, {
                    "perform_time": perform_time,
                    "transaction": transaction_id,
                    "state": 2,
                    "receivers": None
                }))

            # === CancelTransaction ===
            elif method == 'CancelTransaction':
                if not transaction_id:
                    return jsonify(jsonrpc_error(req_id, PaymeError.INVALID_PARAMS, "Missing transaction id"))

                if transaction_id not in processed:
                    return jsonify(jsonrpc_error(req_id, PaymeError.TRANSACTION_NOT_FOUND, "Transaction not found."))

                rec = processed[transaction_id]

                # Идемпотентность: если уже отменена
                if rec.get('state') in [-1, -2]:
                    print(f"↩️ Idempotent CancelTransaction: {transaction_id} (already canceled)")
                    return jsonify(jsonrpc_success(req_id, {
                        "cancel_time": rec['cancel_time'],
                        "transaction": transaction_id,
                        "state": rec['state'],
                        "receivers": None
                    }))

                # Определяем state для отмены
                if rec.get('state') == 1:
                    cancel_state = -1  # Отменена до выполнения
                elif rec.get('state') == 2:
                    cancel_state = -2  # Отменена после выполнения
                else:
                    return jsonify(jsonrpc_error(req_id, PaymeError.CANT_PERFORM, "Cannot cancel transaction in current state."))

                cancel_time = int(time.time() * 1000)
                rec['status'] = "cancelled"
                rec['cancel_time'] = cancel_time
                rec['state'] = cancel_state
                rec['reason'] = params.get('reason')
                processed[transaction_id] = rec
                save_transactions(processed)

                # MQTT для отмены
                topic = f"payments/{MERCHANT_ID}"
                payload = {
                    "status": "cancelled",
                    "amount": rec.get('amount'),
                    "amount_tiyin": rec.get('amount_tiyin'),
                    "currency": "UZS",
                    "transaction_id": transaction_id,
                    "reason": rec.get('reason'),
                    "time": cancel_time
                }
                publish_mqtt(topic, payload, "CancelTransaction")

                print(f"❌ Transaction cancelled: {transaction_id}, reason: {rec.get('reason')}, state: {cancel_state}")

                return jsonify(jsonrpc_success(req_id, {
                    "cancel_time": cancel_time,
                    "transaction": transaction_id,
                    "state": cancel_state,
                    "receivers": None
                }))

            # === CheckTransaction ===
            elif method == 'CheckTransaction':
                if not transaction_id:
                    return jsonify(jsonrpc_error(req_id, PaymeError.INVALID_PARAMS, "Missing transaction id"))

                if transaction_id not in processed:
                    return jsonify(jsonrpc_error(req_id, PaymeError.TRANSACTION_NOT_FOUND, "Transaction not found."))

                t = processed[transaction_id]

                return jsonify(jsonrpc_success(req_id, {
                    "create_time": t.get('create_time'),
                    "perform_time": t.get('perform_time', 0),
                    "cancel_time": t.get('cancel_time', 0),
                    "transaction": transaction_id,
                    "state": t.get('state'),
                    "reason": t.get('reason')
                }))

            # === GetStatement ===
            elif method == 'GetStatement':
                from_time = params.get('from', 0)
                to_time = params.get('to', int(time.time() * 1000))

                transactions_list = []
                for tid, tx in processed.items():
                    if from_time <= tx.get('create_time', 0) <= to_time:
                        transactions_list.append({
                            "id": tid,
                            "time": tx.get('create_time'),
                            "amount": tx.get('amount_tiyin', int(tx.get('amount', 0) * 100)),
                            "account": tx.get('account', {}),
                            "create_time": tx.get('create_time'),
                            "perform_time": tx.get('perform_time', 0),
                            "cancel_time": tx.get('cancel_time', 0),
                            "transaction": tid,
                            "state": tx.get('state'),
                            "reason": tx.get('reason')
                        })

                return jsonify(jsonrpc_success(req_id, {"transactions": transactions_list}))

            else:
                return jsonify(jsonrpc_error(req_id, PaymeError.METHOD_NOT_FOUND, f"Method not found: {method}"))

    except Exception as e:
        print(f"💥 Error processing {method}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify(jsonrpc_error(req_id, PaymeError.SYSTEM_ERROR, "System error"))

# ============ DEBUG/TEST ENDPOINTS ============

@app.route('/test-mqtt', methods=['POST'])
def test_mqtt():
    """Тест MQTT (как в твоём Node.js)"""
    topic = f"payments/{MERCHANT_ID}"
    test_payload = {
        "status": "confirmed",
        "amount": 5000,
        "amount_tiyin": 500000,
        "currency": "UZS",
        "transaction_id": f"test_{int(time.time() * 1000)}",
        "time": int(time.time() * 1000),
        "test": True
    }

    print(f"\n🧪 TEST MQTT: Starting MQTT test")
    print(f"🧪 TEST MQTT: Topic: {topic}")
    print(f"🧪 TEST MQTT: Payload: {test_payload}")
    print(f"🧪 TEST MQTT: MQTT connected: {mqtt_connected}")
    print(f"🧪 TEST MQTT: Broker: {mqtt_url}")

    if not mqtt_connected:
        return jsonify({
            "success": False,
            "error": "MQTT not connected",
            "connected": False,
            "topic": topic,
            "broker": mqtt_url
        }), 500

    success = publish_mqtt(topic, test_payload, "TestMQTT")

    if success:
        return jsonify({
            "success": True,
            "payload": test_payload,
            "topic": topic,
            "broker": mqtt_url,
            "message": "Check ESP32 serial monitor for received message"
        })
    else:
        return jsonify({
            "success": False,
            "error": "MQTT publish failed",
            "topic": topic,
            "broker": mqtt_url
        }), 500

@app.route('/test-full-payment', methods=['POST'])
def test_full_payment():
    """Полный тест оплаты"""
    transaction_id = f"test_payment_{int(time.time() * 1000)}"
    amount = 5000
    amount_tiyin = 500000

    topic = f"payments/{MERCHANT_ID}"
    payload = {
        "status": "confirmed",
        "amount": amount,
        "amount_tiyin": amount_tiyin,
        "currency": "UZS",
        "transaction_id": transaction_id,
        "time": int(time.time() * 1000),
        "test": True,
        "source": "full_payment_test"
    }

    if not mqtt_connected:
        return jsonify({"success": False, "error": "MQTT not connected"}), 500

    success = publish_mqtt(topic, payload, "TestFullPayment")

    return jsonify({
        "success": success,
        "message": "Full payment simulation completed",
        "transaction_id": transaction_id,
        "amount": amount
    })

@app.route('/debug-transactions', methods=['GET'])
def debug_transactions():
    """Просмотр транзакций"""
    processed = load_transactions()
    return jsonify({
        "count": len(processed),
        "transactions": processed
    })

@app.route('/debug-mqtt', methods=['GET'])
def debug_mqtt():
    """Статус MQTT"""
    return jsonify({
        "connected": mqtt_connected,
        "broker": MQTT_BROKER,
        "url": mqtt_url,
        "topics": {
            "payments": f"payments/{MERCHANT_ID}",
            "control": f"control/{MERCHANT_ID}",
            "config": f"config/{MERCHANT_ID}"
        },
        "merchantId": MERCHANT_ID
    })

@app.route('/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({
        "ok": True,
        "mqtt": mqtt_connected,
        "env_merchant": bool(MERCHANT_ID),
        "timestamp": int(time.time() * 1000)
    })

@app.route('/mqtt-status', methods=['GET'])
def mqtt_status():
    """MQTT status"""
    return jsonify({
        "connected": mqtt_connected,
        "broker": MQTT_BROKER,
        "url": mqtt_url,
        "topics": {
            "payments": f"payments/{MERCHANT_ID}",
            "control": f"control/{MERCHANT_ID}",
            "config": f"config/{MERCHANT_ID}"
        },
        "merchantId": MERCHANT_ID
    })

@app.route('/test', methods=['GET'])
def test():
    """Простой тест"""
    return jsonify({
        "status": "ok",
        "message": "Payme webhook server is running",
        "mode": "TEST" if TEST_MODE else "PRODUCTION",
        "mqtt_connected": mqtt_connected,
        "merchant_id": MERCHANT_ID
    })
# ============ ДОБАВЬ ЭТО В app.py ============
# Вставь этот код ПЕРЕД строкой "if __name__ == '__main__':"

# ============ ЗАКАЗЫ ДЛЯ АВТОМАТА ДУХОВ ============
ORDERS_FILE = "orders.json"

def load_orders():
    """Загрузка заказов из файла"""
    try:
        if os.path.exists(ORDERS_FILE):
            with open(ORDERS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"⚠️ Ошибка загрузки заказов: {e}")
    return {}

def save_orders(data):
    """Сохранение заказов в файл"""
    try:
        with open(ORDERS_FILE, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Ошибка сохранения заказов: {e}")

@app.route('/api/create-perfume-order', methods=['POST'])
def create_perfume_order():
    """
    Создание заказа для автомата духов.
    ESP32 вызывает этот endpoint, получает QR URL.
    """
    try:
        data = request.json or {}
        device_id = data.get('device_id', 'unknown')
        parfum_id = data.get('parfum_id', 1)
        amount = data.get('amount', 5000)  # сумма в сумах

        # Генерируем уникальный ID заказа
        order_id = f"parfum_{int(time.time())}_{parfum_id}"
        amount_tiyin = amount * 100

        print(f"\n📦 Creating perfume order:")
        print(f"   Device: {device_id}")
        print(f"   Parfum: {parfum_id}")
        print(f"   Amount: {amount} сум")

        # Генерируем Payme checkout URL
        # Формат: m=MERCHANT_ID;ac.order_id=ORDER_ID;a=AMOUNT_TIYIN
        params = f"m={MERCHANT_ID};ac.StreetAroma=Aroma;a={amount_tiyin}"
        encoded_params = base64.b64encode(params.encode()).decode()

        # URL для QR кода
        qr_url = f"https://checkout.paycom.uz/{encoded_params}"

        print(f"   QR URL: {qr_url}")

        # Сохраняем заказ
        orders = load_orders()
        orders[order_id] = {
            "order_id": order_id,
            "device_id": device_id,
            "parfum_id": parfum_id,
            "amount": amount,
            "amount_tiyin": amount_tiyin,
            "qr_url": qr_url,
            "status": "pending",
            "created_at": int(time.time() * 1000)
        }
        save_orders(orders)

        # Отправляем MQTT на ESP32 с QR URL
        topic = f"payments/{MERCHANT_ID}"
        mqtt_payload = {
            "status": "created",
            "order_id": order_id,
            "parfum_id": parfum_id,
            "amount": amount,
            "amount_tiyin": amount_tiyin,
            "qr_url": qr_url,
            "time": int(time.time() * 1000)
        }

        publish_mqtt(topic, mqtt_payload, "CreatePerfumeOrder")

        print(f"✅ Order created: {order_id}")

        return jsonify({
            "success": True,
            "order_id": order_id,
            "parfum_id": parfum_id,
            "amount": amount,
            "qr_url": qr_url
        })

    except Exception as e:
        print(f"❌ Error creating order: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/cancel-perfume-order', methods=['POST'])
def cancel_perfume_order():
    """Отмена заказа"""
    try:
        data = request.json or {}
        order_id = data.get('order_id')

        if not order_id:
            return jsonify({"success": False, "error": "Missing order_id"}), 400

        orders = load_orders()

        if order_id in orders:
            orders[order_id]['status'] = 'cancelled'
            save_orders(orders)

            # MQTT уведомление
            topic = f"payments/{MERCHANT_ID}"
            mqtt_payload = {
                "status": "cancelled",
                "order_id": order_id,
                "time": int(time.time() * 1000)
            }
            publish_mqtt(topic, mqtt_payload, "CancelPerfumeOrder")

            print(f"❌ Order cancelled: {order_id}")

            return jsonify({"success": True, "order_id": order_id})
        else:
            return jsonify({"success": False, "error": "Order not found"}), 404

    except Exception as e:
        print(f"❌ Error cancelling order: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/orders', methods=['GET'])
def get_orders():
    """Получение списка заказов"""
    orders = load_orders()
    return jsonify({
        "count": len(orders),
        "orders": orders
    })
def set_prices():
    """Установка цен парфюмов (админ)"""
    try:
        data = request.json or {}
        prices = data.get('prices', [])

        # Тут можно сохранить в файл
        print(f"📝 Prices updated: {prices}")

        return jsonify({"success": True, "prices": prices})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
# ============ ЦЕНЫ ПАРФЮМОВ ============
PRICES_FILE = "prices.json"

def load_prices():
    try:
        if os.path.exists(PRICES_FILE):
            with open(PRICES_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {
        "prices": [5000, 6000, 7000, 8000],
        "names": ["Tom Ford", "Lanvin", "Dior", "Dolce Gabbana"]
    }

def save_prices(data):
    with open(PRICES_FILE, 'w') as f:
        json.dump(data, f, indent=2)

@app.route('/api/prices', methods=['GET'])
def get_prices():
    """ESP32 получает цены"""
    return jsonify(load_prices())

@app.route('/api/prices', methods=['POST'])
def set_prices():
    """Админ меняет цены"""
    data = request.json or {}
    prices = load_prices()

    if 'prices' in data:
        prices['prices'] = data['prices']
    if 'names' in data:
        prices['names'] = data['names']

    save_prices(prices)
    print(f"📝 Prices updated: {prices}")

    return jsonify({"success": True, "prices": prices})
# ============ STARTUP ============
if __name__ == '__main__':
    print(f"""
╔══════════════════════════════════════════════════════╗
║     🚀 Payme Webhook Server запущен 🚀              ║
╠══════════════════════════════════════════════════════╣
║  Endpoint: /payme-mqtt
║  Mode: {"TEST" if TEST_MODE else "PRODUCTION"}
║  Merchant ID: {MERCHANT_ID}
║  MQTT Broker: {mqtt_url}
║  MQTT Topic: payments/{MERCHANT_ID}
╠══════════════════════════════════════════════════════╣
║  Debug endpoints:
║    - GET  /health
║    - GET  /mqtt-status
║    - POST /test-mqtt
║    - POST /test-full-payment
║    - GET  /debug-transactions
║    - GET  /debug-mqtt
╚══════════════════════════════════════════════════════╝
""")

    app.run(host='0.0.0.0', port=3002, debug=True)
