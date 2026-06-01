import base64
import requests
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from db import get_db

mpesa_bp = Blueprint("mpesa", __name__)


# Helper: get Daraja OAuth token 
def get_mpesa_token():
    consumer_key    = current_app.config["MPESA_CONSUMER_KEY"]
    consumer_secret = current_app.config["MPESA_CONSUMER_SECRET"]
    base_url        = current_app.config["MPESA_BASE_URL"]

    credentials = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()

    response = requests.get(
        f"{base_url}/oauth/v1/generate?grant_type=client_credentials",
        headers={"Authorization": f"Basic {credentials}"},
        timeout=10,
    )
    response.raise_for_status()
    return response.json().get("access_token")


#  Helper: generate Lipa Na Mpesa password 
def generate_password(shortcode, passkey):
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    raw       = f"{shortcode}{passkey}{timestamp}"
    password  = base64.b64encode(raw.encode()).decode()
    return password, timestamp



#  POST /api/mpesa/stk-push
#  Initiate STK push for an order
@mpesa_bp.route("/stk-push", methods=["POST"])
@jwt_required()
def stk_push():
    user_id  = get_jwt_identity()
    data     = request.get_json()
    order_id = data.get("order_id")
    phone    = data.get("phone")  # Kenyan format: 2547XXXXXXXX

    if not order_id or not phone:
        return jsonify({"error": "order_id and phone are required"}), 400

    # Normalize phone number: 07... → 2547...
    phone = str(phone).strip()
    if phone.startswith("0"):
        phone = "254" + phone[1:]
    elif phone.startswith("+"):
        phone = phone[1:]

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    # Validate order belongs to user and is pending
    cursor.execute("""
        SELECT order_id, total_amount, status
        FROM orders WHERE order_id=%s AND user_id=%s
    """, (order_id, user_id))
    order = cursor.fetchone()

    if not order:
        cursor.close()
        return jsonify({"error": "Order not found"}), 404

    if order["status"] not in ("pending",):
        cursor.close()
        return jsonify({"error": f"Order cannot be paid. Status: {order['status']}"}), 400

    amount    = int(float(order["total_amount"]))  # Must be integer for Mpesa
    shortcode = current_app.config["MPESA_SHORTCODE"]
    passkey   = current_app.config["MPESA_PASSKEY"]
    base_url  = current_app.config["MPESA_BASE_URL"]
    callback  = current_app.config["MPESA_CALLBACK_URL"]

    try:
        token              = get_mpesa_token()
        password, timestamp = generate_password(shortcode, passkey)

        payload = {
            "BusinessShortCode": 542542,
            "Password":          password,
            "Timestamp":         timestamp,
            "TransactionType":   "CustomerPayBillOnline",
            "Amount":            amount,
            "PartyA":            phone,               # Customer phone
            "PartyB":            542542,            # Paybill number
            "PhoneNumber":       phone,
            "CallBackURL":       callback,
            "AccountReference":  "Sokoni-Order-{order_id}",
            "TransactionDesc":   f"Payment for Sokoni Order #{order_id}",
        }

        resp = requests.post(
            f"{base_url}/mpesa/stkpush/v1/processrequest",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        mpesa_resp = resp.json()

    except requests.RequestException as e:
        current_app.logger.error(f"[MPESA] STK push error: {e}")
        return jsonify({"error": "Failed to initiate payment. Please try again."}), 502

    if mpesa_resp.get("ResponseCode") == "0":
        checkout_id = mpesa_resp.get("CheckoutRequestID")
        # Save checkout request ID for reconciliation via callback
        cursor.execute("""
            UPDATE orders SET mpesa_checkout_id=%s WHERE order_id=%s
        """, (checkout_id, order_id))
        db.commit()
        cursor.close()

        return jsonify({
            "message":           "STK push sent. Please enter your Mpesa PIN on your phone.",
            "checkout_request_id": checkout_id,
            "merchant_request_id": mpesa_resp.get("MerchantRequestID"),
        }), 200
    else:
        cursor.close()
        return jsonify({
            "error":       "Mpesa request failed",
            "mpesa_error": mpesa_resp.get("errorMessage", "Unknown error"),
        }), 400


#  POST /api/mpesa/callback
#  Safaricom calls this after payment
@mpesa_bp.route("/callback", methods=["POST"])
def mpesa_callback():
    payload = request.get_json(silent=True) or {}
    current_app.logger.info(f"[MPESA CALLBACK] {payload}")

    try:
        body    = payload["Body"]["stkCallback"]
        code    = body["ResultCode"]
        checkout_id = body["CheckoutRequestID"]

        db     = get_db()
        cursor = db.cursor(dictionary=True)

        if code == 0:
            # Payment successful — extract receipt from callback metadata
            items = body["CallbackMetadata"]["Item"]
            meta  = {i["Name"]: i.get("Value") for i in items}

            receipt  = meta.get("MpesaReceiptNumber")
            # amount = meta.get("Amount")

            cursor.execute("""
                UPDATE orders
                SET status='paid', mpesa_receipt=%s
                WHERE mpesa_checkout_id=%s
            """, (receipt, checkout_id))
            db.commit()
            current_app.logger.info(f"[MPESA] Payment confirmed. Receipt: {receipt}")
        else:
            # Payment failed or cancelled
            result_desc = body.get("ResultDesc", "")
            current_app.logger.warning(f"[MPESA] Payment failed: {result_desc}")
            # Leave order as 'pending' — user can retry

        cursor.close()
    except (KeyError, TypeError) as e:
        current_app.logger.error(f"[MPESA CALLBACK] Parse error: {e}")

    # Always return 200 to Safaricom
    return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200


# ─────────────────────────────────────────
#  POST /api/mpesa/stk-query
#  Manually query STK push status
# ─────────────────────────────────────────
@mpesa_bp.route("/stk-query", methods=["POST"])
@jwt_required()
def stk_query():
    data        = request.get_json()
    checkout_id = data.get("checkout_request_id")

    if not checkout_id:
        return jsonify({"error": "checkout_request_id is required"}), 400

    shortcode = current_app.config["MPESA_SHORTCODE"]
    passkey   = current_app.config["MPESA_PASSKEY"]
    base_url  = current_app.config["MPESA_BASE_URL"]

    try:
        token              = get_mpesa_token()
        password, timestamp = generate_password(shortcode, passkey)

        resp = requests.post(
            f"{base_url}/mpesa/stkpushquery/v1/query",
            json={
                "BusinessShortCode": shortcode,
                "Password":          password,
                "Timestamp":         timestamp,
                "CheckoutRequestID": checkout_id,
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return jsonify(resp.json()), 200

    except requests.RequestException as e:
        current_app.logger.error(f"[MPESA QUERY] Error: {e}")
        return jsonify({"error": "Query failed"}), 502


#  POST /api/mpesa/stk-push-guest
#  Initiate STK push for a guest order (no auth required)
@mpesa_bp.route("/stk-push-guest", methods=["POST"])
def stk_push_guest():
    data     = request.get_json() or {}
    order_id = data.get("order_id")
    phone    = str(data.get("phone", "")).strip()

    if not order_id or not phone:
        return jsonify({"error": "order_id and phone are required"}), 400

    if phone.startswith("0"):
        phone = "254" + phone[1:]
    elif phone.startswith("+"):
        phone = phone[1:]

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    # Only allow guest (user_id IS NULL) pending orders
    cursor.execute(
        "SELECT order_id, total_amount, status FROM orders WHERE order_id=%s AND user_id IS NULL",
        (order_id,)
    )
    order = cursor.fetchone()
    if not order:
        cursor.close()
        return jsonify({"error": "Guest order not found"}), 404
    if order["status"] != "pending":
        cursor.close()
        return jsonify({"error": f"Order already {order['status']}"}), 400

    amount    = int(float(order["total_amount"]))
    shortcode = current_app.config["MPESA_SHORTCODE"]
    passkey   = current_app.config["MPESA_PASSKEY"]
    base_url  = current_app.config["MPESA_BASE_URL"]
    callback  = current_app.config["MPESA_CALLBACK_URL"]

    try:
        token               = get_mpesa_token()
        password, timestamp = generate_password(shortcode, passkey)
        payload = {
            "BusinessShortCode": shortcode,
            "Password":          password,
            "Timestamp":         timestamp,
            "TransactionType":   "CustomerPayBillOnline",
            "Amount":            amount,
            "PartyA":            phone,
            "PartyB":            shortcode,
            "PhoneNumber":       phone,
            "CallBackURL":       callback,
            "AccountReference":  f"Sokoni-{order_id}",
            "TransactionDesc":   f"Payment for Sokoni Order #{order_id}",
        }
        resp = requests.post(
            f"{base_url}/mpesa/stkpush/v1/processrequest",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        mpesa_resp = resp.json()
    except requests.RequestException as e:
        current_app.logger.error(f"[MPESA GUEST] STK error: {e}")
        cursor.close()
        return jsonify({"error": "Failed to initiate payment. Please try again."}), 502

    if mpesa_resp.get("ResponseCode") == "0":
        checkout_id = mpesa_resp.get("CheckoutRequestID")
        cursor.execute(
            "UPDATE orders SET mpesa_checkout_id=%s WHERE order_id=%s",
            (checkout_id, order_id)
        )
        db.commit()
        cursor.close()
        return jsonify({
            "message":             "STK push sent. Check your phone for the M-Pesa prompt.",
            "checkout_request_id": checkout_id,
        }), 200
    else:
        cursor.close()
        return jsonify({
            "error":       "M-Pesa request failed",
            "mpesa_error": mpesa_resp.get("errorMessage", "Unknown error"),
        }), 400