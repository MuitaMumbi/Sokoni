"""
routes/mpesa.py — Sokoni M-Pesa Payment Routes
Paybill: I&M Bank shortcode via Safaricom Daraja API

Routes:
  POST /api/mpesa/stk-push          — authenticated STK push (logged-in user)
  POST /api/mpesa/stk-push-guest    — guest STK push (no auth)
  POST /api/mpesa/callback          — Safaricom async callback (webhook)
  POST /api/mpesa/stk-query         — query STK push status via Daraja
  GET  /api/mpesa/order-status/<id> — poll order payment status (frontend polling)
  POST /api/mpesa/c2b/validate      — C2B validation (manual Paybill fallback)
  POST /api/mpesa/c2b/confirm       — C2B confirmation (manual Paybill fallback)
"""

import base64
import logging
import requests
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from db import get_db

mpesa_bp = Blueprint("mpesa", __name__)
logger = logging.getLogger("sokoni")

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_mpesa_token() -> str:
    """Fetch OAuth2 access token from Daraja."""
    consumer_key    = current_app.config["MPESA_CONSUMER_KEY"]
    consumer_secret = current_app.config["MPESA_CONSUMER_SECRET"]
    base_url        = current_app.config["MPESA_BASE_URL"]

    credentials = base64.b64encode(
        f"{consumer_key}:{consumer_secret}".encode()
    ).decode()

    resp = requests.get(
        f"{base_url}/oauth/v1/generate?grant_type=client_credentials",
        headers={"Authorization": f"Basic {credentials}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def generate_password(shortcode: str, passkey: str) -> tuple[str, str]:
    """Return (base64_password, timestamp) for STK push requests."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    raw       = f"{shortcode}{passkey}{timestamp}"
    password  = base64.b64encode(raw.encode()).decode()
    return password, timestamp


COUNTRY_CODES = {
    "Kenya":    "254",
    "Tanzania": "255",
    "Uganda":   "256",
    "Rwanda":   "250",
    "Ethiopia": "251",
}

def normalize_phone(phone: str, country: str = "Kenya") -> str:
    """Normalise any local phone format to E.164 (no +). e.g. 0712345678 → 254712345678"""
    phone = str(phone).strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        phone = phone[1:]
    code = COUNTRY_CODES.get(country, "254")
    if phone.startswith(code):
        return phone
    if phone.startswith("0"):
        return code + phone[1:]
    return code + phone


def _stk_payload(shortcode, passkey, phone, amount, order_id, callback_url) -> dict:
    """Build a reusable STK push payload dict."""
    password, timestamp = generate_password(shortcode, passkey)
    return {
        "BusinessShortCode": shortcode,
        "Password":          password,
        "Timestamp":         timestamp,
        "TransactionType":   "CustomerPayBillOnline",
        "Amount":            amount,
        "PartyA":            phone,
        "PartyB":            shortcode,
        "PhoneNumber":       phone,
        "CallBackURL":       callback_url,
        "AccountReference":  f"Sokoni-{order_id}",
        "TransactionDesc":   f"Payment for Sokoni Order #{order_id}",
    }


def _do_stk_push(payload: dict) -> dict:
    """Send the STK push request to Daraja. Returns the JSON response."""
    token    = get_mpesa_token()
    base_url = current_app.config["MPESA_BASE_URL"]

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
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE 1: STK Push — authenticated user
# ─────────────────────────────────────────────────────────────────────────────

@mpesa_bp.route("/stk-push", methods=["POST"])
@jwt_required()
def stk_push():
    """
    Trigger STK push for a logged-in user's pending order.

    Body: { "order_id": 123, "phone": "0712345678" }
    """
    user_id  = get_jwt_identity()
    data     = request.get_json() or {}
    order_id = data.get("order_id")
    phone    = str(data.get("phone", "")).strip()

    if not order_id or not phone:
        return jsonify({"error": "order_id and phone are required"}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT order_id, total_amount, status, country
        FROM orders
        WHERE order_id = %s AND user_id = %s
    """, (order_id, user_id))
    order = cursor.fetchone()

    if not order:
        cursor.close()
        return jsonify({"error": "Order not found"}), 404

    if order["status"] != "pending":
        cursor.close()
        return jsonify({"error": f"Order cannot be paid — status is '{order['status']}'"}), 400

    phone  = normalize_phone(phone, order.get("country", "Kenya"))
    amount = int(float(order["total_amount"]))

    shortcode = current_app.config["MPESA_SHORTCODE"]
    passkey   = current_app.config["MPESA_PASSKEY"]
    callback  = current_app.config["MPESA_CALLBACK_URL"]

    try:
        payload    = _stk_payload(shortcode, passkey, phone, amount, order_id, callback)
        mpesa_resp = _do_stk_push(payload)
    except requests.RequestException as e:
        logger.error(f"[MPESA] STK push error: {e}")
        cursor.close()
        return jsonify({"error": "Payment gateway unreachable. Please try again."}), 502

    if mpesa_resp.get("ResponseCode") == "0":
        checkout_id = mpesa_resp["CheckoutRequestID"]
        cursor.execute("""
            UPDATE orders SET mpesa_checkout_id = %s WHERE order_id = %s
        """, (checkout_id, order_id))
        db.commit()
        cursor.close()

        logger.info(f"[MPESA] STK push sent | order={order_id} checkout={checkout_id}")
        return jsonify({
            "message":             "M-Pesa prompt sent. Enter your PIN to complete payment.",
            "checkout_request_id": checkout_id,
            "merchant_request_id": mpesa_resp.get("MerchantRequestID"),
        }), 200

    cursor.close()
    logger.warning(f"[MPESA] STK push rejected: {mpesa_resp}")
    return jsonify({
        "error":       "M-Pesa request failed",
        "mpesa_error": mpesa_resp.get("errorMessage", mpesa_resp.get("ResponseDescription", "Unknown error")),
    }), 400


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE 2: STK Push — guest (no JWT)
# ─────────────────────────────────────────────────────────────────────────────

@mpesa_bp.route("/stk-push-guest", methods=["POST"])
def stk_push_guest():
    """
    Trigger STK push for a guest (unauthenticated) pending order.

    Body: { "order_id": 123, "phone": "0712345678" }
    """
    data     = request.get_json() or {}
    order_id = data.get("order_id")
    phone    = str(data.get("phone", "")).strip()

    if not order_id or not phone:
        return jsonify({"error": "order_id and phone are required"}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT order_id, total_amount, status, country
        FROM orders
        WHERE order_id = %s AND user_id IS NULL
    """, (order_id,))
    order = cursor.fetchone()

    if not order:
        cursor.close()
        return jsonify({"error": "Guest order not found"}), 404

    if order["status"] != "pending":
        cursor.close()
        return jsonify({"error": f"Order already {order['status']}"}), 400

    phone  = normalize_phone(phone, order.get("country", "Kenya"))
    amount = int(float(order["total_amount"]))

    shortcode = current_app.config["MPESA_SHORTCODE"]
    passkey   = current_app.config["MPESA_PASSKEY"]
    callback  = current_app.config["MPESA_CALLBACK_URL"]

    try:
        payload    = _stk_payload(shortcode, passkey, phone, amount, order_id, callback)
        mpesa_resp = _do_stk_push(payload)
    except requests.RequestException as e:
        logger.error(f"[MPESA GUEST] STK push error: {e}")
        cursor.close()
        return jsonify({"error": "Failed to initiate payment. Please try again."}), 502

    if mpesa_resp.get("ResponseCode") == "0":
        checkout_id = mpesa_resp["CheckoutRequestID"]
        cursor.execute("""
            UPDATE orders SET mpesa_checkout_id = %s WHERE order_id = %s
        """, (checkout_id, order_id))
        db.commit()
        cursor.close()

        logger.info(f"[MPESA GUEST] STK push sent | order={order_id} checkout={checkout_id}")
        return jsonify({
            "message":             "M-Pesa prompt sent. Check your phone and enter your PIN.",
            "checkout_request_id": checkout_id,
        }), 200

    cursor.close()
    return jsonify({
        "error":       "M-Pesa request failed",
        "mpesa_error": mpesa_resp.get("errorMessage", "Unknown error"),
    }), 400


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE 3: Safaricom Callback (webhook — NO auth, NO rate limit)
# ─────────────────────────────────────────────────────────────────────────────

@mpesa_bp.route("/callback", methods=["POST"])
def mpesa_callback():
    """
    Safaricom calls this URL asynchronously after every STK push attempt.
    result_code == 0  → payment successful
    result_code != 0  → cancelled or failed (leave order as 'pending' so user can retry)

    IMPORTANT: Always return HTTP 200 with {"ResultCode": 0} or Safaricom will retry.
    """
    payload = request.get_json(silent=True) or {}
    logger.info(f"[MPESA CALLBACK] Raw payload: {payload}")

    try:
        body        = payload["Body"]["stkCallback"]
        result_code = body["ResultCode"]
        checkout_id = body["CheckoutRequestID"]

        db     = get_db()
        cursor = db.cursor(dictionary=True)

        if result_code == 0:
            # ── Payment successful ──
            items = body.get("CallbackMetadata", {}).get("Item", [])
            meta  = {i["Name"]: i.get("Value") for i in items}

            receipt          = meta.get("MpesaReceiptNumber")
            amount_confirmed = meta.get("Amount")
            phone_paid       = str(meta.get("PhoneNumber", ""))
            txn_date         = str(meta.get("TransactionDate", ""))

            cursor.execute("""
                UPDATE orders
                SET status = 'paid',
                    mpesa_receipt = %s,
                    paid_at = NOW()
                WHERE mpesa_checkout_id = %s
            """, (receipt, checkout_id))
            db.commit()

            logger.info(
                f"[MPESA] ✅ Payment confirmed | receipt={receipt} "
                f"amount={amount_confirmed} phone={phone_paid} date={txn_date}"
            )

            # ── TODO: trigger post-payment actions here ──
            # notify_user(checkout_id)
            # update_inventory(checkout_id)
            # send_order_confirmation_email(checkout_id)

        else:
            # ── Payment failed or cancelled ──
            result_desc = body.get("ResultDesc", "No description")
            logger.warning(
                f"[MPESA] ❌ Payment failed | checkout={checkout_id} "
                f"code={result_code} desc='{result_desc}'"
            )
            # Do NOT change order status — let the user retry

        cursor.close()

    except (KeyError, TypeError) as e:
        logger.error(f"[MPESA CALLBACK] Failed to parse payload: {e} | raw={payload}")

    # Always return 200 to Safaricom — non-200 causes repeated retries
    return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE 4: STK Query — check status via Daraja API
# ─────────────────────────────────────────────────────────────────────────────

@mpesa_bp.route("/stk-query", methods=["POST"])
@jwt_required()
def stk_query():
    """
    Directly query Daraja for the status of an STK push.
    Use this as a fallback when the callback hasn't arrived yet.

    Body: { "checkout_request_id": "ws_CO_..." }
    """
    data        = request.get_json() or {}
    checkout_id = data.get("checkout_request_id")

    if not checkout_id:
        return jsonify({"error": "checkout_request_id is required"}), 400

    shortcode = current_app.config["MPESA_SHORTCODE"]
    passkey   = current_app.config["MPESA_PASSKEY"]
    base_url  = current_app.config["MPESA_BASE_URL"]

    try:
        token               = get_mpesa_token()
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
        daraja_result = resp.json()

    except requests.RequestException as e:
        logger.error(f"[MPESA QUERY] Request error: {e}")
        return jsonify({"error": "STK query failed. Try again."}), 502

    # ResultCode 0 = success, 1032 = cancelled by user, 1037 = timeout
    result_code = daraja_result.get("ResultCode")
    return jsonify({
        "checkout_request_id": checkout_id,
        "result_code":         result_code,
        "result_desc":         daraja_result.get("ResultDesc"),
        "paid":                result_code == "0",
    }), 200


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE 5: Order payment status — frontend polling endpoint
# ─────────────────────────────────────────────────────────────────────────────

@mpesa_bp.route("/order-status/<int:order_id>", methods=["GET"])
@jwt_required()
def order_payment_status(order_id: int):
    """
    Lightweight polling endpoint for the frontend.
    Call every 3–5 seconds after STK push until status != 'pending'.

    Returns: { "status": "pending" | "paid" | "failed" | "cancelled", ... }
    """
    user_id = get_jwt_identity()

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT order_id, status, total_amount, mpesa_receipt, paid_at
        FROM orders
        WHERE order_id = %s AND (user_id = %s OR user_id IS NULL)
    """, (order_id, user_id))
    order = cursor.fetchone()
    cursor.close()

    if not order:
        return jsonify({"error": "Order not found"}), 404

    response = {
        "order_id": order["order_id"],
        "status":   order["status"],
        "amount":   str(order["total_amount"]),
    }

    if order["status"] == "paid":
        response["mpesa_receipt"] = order.get("mpesa_receipt")
        response["paid_at"]       = str(order.get("paid_at", ""))

    return jsonify(response), 200


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE 6 & 7: C2B — manual Paybill entry fallback
# ─────────────────────────────────────────────────────────────────────────────

# @mpesa_bp.route("/c2b/validate", methods=["POST"])
# def c2b_validate():
#     """
#     Safaricom calls this BEFORE processing a manual Paybill payment.
#     Validate the account reference (BillRefNumber) is a real order.
#     Return ResultCode "0" to accept, "C2B00012" to reject.

#     Register this URL on Daraja: C2B API → Validation URL.
#     """
#     data     = request.get_json(force=True, silent=True) or {}
#     bill_ref = data.get("BillRefNumber", "")
#     amount   = data.get("TransAmount", 0)
#     phone    = data.get("MSISDN", "")

#     logger.info(f"[C2B VALIDATE] ref={bill_ref} amount={amount} phone={phone}")

#     # Validate the order reference exists and is pending
#     db     = get_db()
#     cursor = db.cursor(dictionary=True)

#     # BillRefNumber will be whatever the customer typed as account number
#     # Convention: customers enter their order_id e.g. "12345"
#     cursor.execute("""
#         SELECT order_id, status, total_amount
#         FROM orders
#         WHERE order_id = %s
#     """, (bill_ref,))
#     order = cursor.fetchone()
#     cursor.close()

#     if not order:
#         logger.warning(f"[C2B VALIDATE] Order not found: {bill_ref}")
#         return jsonify({"ResultCode": "C2B00012", "ResultDesc": "Order not found"}), 200

#     if order["status"] != "pending":
#         logger.warning(f"[C2B VALIDATE] Order not payable: {bill_ref} status={order['status']}")
#         return jsonify({"ResultCode": "C2B00012", "ResultDesc": "Order already paid or cancelled"}), 200

#     return jsonify({"ResultCode": "0", "ResultDesc": "Accepted"}), 200


# @mpesa_bp.route("/c2b/confirm", methods=["POST"])
# def c2b_confirm():
#     """
#     Safaricom calls this AFTER a successful manual Paybill payment.
#     Payment is already processed at this point — just record it.

#     Register this URL on Daraja: C2B API → Confirmation URL.
#     """
#     data     = request.get_json(force=True, silent=True) or {}
#     receipt  = data.get("TransID", "")
#     amount   = data.get("TransAmount", 0)
#     phone    = str(data.get("MSISDN", ""))
#     bill_ref = data.get("BillRefNumber", "")   # order_id the customer typed
#     txn_time = data.get("TransTime", "")

#     logger.info(
#         f"[C2B CONFIRM] receipt={receipt} amount={amount} "
#         f"phone={phone} ref={bill_ref}"
#     )

#     db     = get_db()
#     cursor = db.cursor(dictionary=True)

#     cursor.execute("""
#         UPDATE orders
#         SET status = 'paid',
#             mpesa_receipt = %s,
#             paid_at = NOW()
#         WHERE order_id = %s AND status = 'pending'
#     """, (receipt, bill_ref))
#     db.commit()

#     if cursor.rowcount == 0:
#         logger.warning(f"[C2B CONFIRM] No pending order updated for ref={bill_ref}")
#     else:
#         logger.info(f"[C2B CONFIRM] ✅ Order {bill_ref} marked paid | receipt={receipt}")
#         # ── TODO: trigger post-payment actions here ──
#         # notify_user_c2b(bill_ref, receipt)

#     cursor.close()

#     # Always return 200 to Safaricom
#     return jsonify({"ResultCode": "0", "ResultDesc": "Accepted"}), 200