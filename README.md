# 🛒 Sokoni — E-commerce Backend API

Python (Flask) + MySQL backend for the **Sokoni** mobile commerce application, featuring JWT authentication, email activation codes, product management, cart, orders, and **Mpesa STK Push** (Paybill) integration.

---

## 📁 Project Structure

```
sokoni/
├── app.py                  # App entry point
├── config.py               # All configuration & env vars
├── db.py                   # DB connection + table creation
├── schema.sql              # Raw SQL schema (optional direct import)
├── requirements.txt
├── .env.example            # Copy to .env and fill in values
├── routes/
│   ├── auth.py             # Sign up, activate, sign in
│   ├── products.py         # CRUD products
│   ├── cart.py             # Cart management
│   ├── orders.py           # Order placement & tracking
│   └── mpesa.py            # STK Push, callback, query
└── utils/
    └── email_utils.py      # Activation code emails
```

---

## ⚙️ Setup

### 1. Clone & install dependencies

```bash
cd sokoni
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your MySQL credentials, email settings, and Mpesa keys
```

### 3. Start MySQL and run the app

```bash
# Tables are auto-created on first run
python app.py
```

Or import the schema manually:
```bash
mysql -u root -p < schema.sql
```

---

## 🔐 Authentication Flow

```
POST /api/auth/signup        → Register (sends 6-digit code to email)
POST /api/auth/activate      → Verify code → account activated
POST /api/auth/resend-code   → Resend activation code
POST /api/auth/signin        → Get JWT token
GET  /api/auth/me            → View own profile (JWT required)
```

---

## 📦 Products API

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/products/` | Admin JWT | Add product (multipart with photo) |
| GET | `/api/products/` | Public | List products (search, page, limit) |
| GET | `/api/products/<id>` | Public | Single product |
| PUT | `/api/products/<id>` | Admin JWT | Update product |
| DELETE | `/api/products/<id>` | Admin JWT | Delete product |

### Add Product (multipart/form-data)
```
product_name    string   required
product_cost    float    required
product_desc    string   optional
stock           int      optional (default 0)
product_photo   file     optional (jpg/png/webp/gif, max 5MB)
```

---

## 🛒 Cart API  *(JWT required)*

```
GET    /api/cart/            → View cart with totals
POST   /api/cart/            → Add item  { product_id, quantity }
PUT    /api/cart/<cart_id>   → Update quantity  { quantity }
DELETE /api/cart/<cart_id>   → Remove item
DELETE /api/cart/clear       → Clear entire cart
```

---

## 📋 Orders API  *(JWT required)*

```
POST  /api/orders/                    → Place order from cart
GET   /api/orders/                    → My orders
GET   /api/orders/<id>                → Order detail + items
PATCH /api/orders/<id>/status         → Update status (admin only)
```

**Order statuses:** `pending → paid → shipped → delivered | cancelled`

---

## 💳 Mpesa STK Push (Paybill)

### Initiate payment
```
POST /api/mpesa/stk-push
Authorization: Bearer <token>

{
  "order_id": 1,
  "phone": "0712345678"    // or 254712345678
}
```

A push notification appears on the customer's phone. They enter their PIN → Safaricom calls your callback URL.

### Callback (called by Safaricom)
```
POST /api/mpesa/callback
```
On success, the order status is automatically updated to `paid` and the M-Pesa receipt number is stored.

### Query payment status
```
POST /api/mpesa/stk-query
{ "checkout_request_id": "ws_CO_..." }
```

---

## 🗄️ Database Schema

```
users         user_id, username, email, phone, password, is_active,
              activation_code, activation_expires, role, created_at

products      product_id, product_name, product_cost, product_desc,
              product_photo, stock, created_by, created_at

cart          cart_id, user_id, product_id, quantity, added_at

orders        order_id, user_id, total_amount, status,
              mpesa_checkout_id, mpesa_receipt, created_at

order_items   item_id, order_id, product_id, quantity, unit_price
```

---

## 🌍 Mpesa Setup (Daraja)

1. Register at [developer.safaricom.co.ke](https://developer.safaricom.co.ke/)
2. Create an app → get **Consumer Key** and **Consumer Secret**
3. Get your **Paybill Shortcode** and **Lipa Na Mpesa Passkey** from the portal
4. Set `MPESA_BASE_URL=https://sandbox.safaricom.co.ke` for testing
5. Use **ngrok** to expose your local callback URL during development:
   ```bash
   ngrok http 5000
   # Then set MPESA_CALLBACK_URL=https://xxxx.ngrok.io/api/mpesa/callback
   ```
6. Switch to `https://api.safaricom.co.ke` for production

---

## 👤 Roles

| Role | Capabilities |
|------|-------------|
| `customer` | Sign up, browse, cart, orders, pay |
| `admin` | All above + add/edit/delete products, update order status |

To make a user an admin, update their role in MySQL:
```sql
UPDATE users SET role='admin' WHERE email='you@example.com';
```

---

## 🚀 Production Checklist

- [ ] Set `DEBUG=False`
- [ ] Use strong random `SECRET_KEY` and `JWT_SECRET_KEY`
- [ ] Switch Mpesa base URL to live (`https://api.safaricom.co.ke`)
- [ ] Use a production WSGI server: `gunicorn app:app`
- [ ] Serve uploaded images via Nginx, not Flask
- [ ] Add HTTPS (Let's Encrypt / Nginx)
- [ ] Remove `activation_code_dev` from signup response
