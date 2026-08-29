# 💸 Refund Status Flow — API + Webhooks

Everything a backend/frontend/POSTMAN tester needs to verify the new refund system.

## 1. Refund Status Flow (replaces the old ambiguous `"refunded"`)

| Stage | `order.payment_status` | Who sets it | When |
|-------|------------------------|-------------|------|
| Payment received | `paid` | webhook / payment confirm | After payment captured |
| 🟡 Refund initiated | `refund_initiated` | refund service (`process_refund`) | Immediately after calling the Razorpay refund API in live mode (provider returns `pending`) |
| 🟢 Refund completed | `refund_completed` | refund service **or** webhook `refund.processed` | Instantly in test/dummy mode (provider returns `processed`), or later when the **money actually reaches the bank** (webhook) |
| 🔴 Refund failed | `refund_failed` | webhook `refund.failed` | If Razorpay reports the refund failed |

```
TEST MODE (PAYMENT_PROVIDER=dummy)              LIVE MODE (razorpay, 1-5 days)
─────────────────────────────────               ─────────────────────────────────
1. Cancel order                                 1. Cancel order
2. Dummy refund API → "processed"               2. Razorpay refund API → "pending"
3. payment_status = refund_completed ✅          3. payment_status = refund_initiated 🟡
                                                  4. (1-5 days pass)
                                                  5. Razorpay webhook: refund.processed
                                                  6. payment_status = refund_completed ✅
```

> ⚠️ **Legacy status `"refunded"` is no longer written.** Any order that already has
> `"refunded"` in the DB keeps working — treat it as `refund_completed` in the UI.

## 2. Endpoints

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| `POST` | `/api/v1/orders/{order_id}/cancel` | 🔑 User Bearer | Cancel + initiate refund for a paid online order |
| `GET` | `/api/v1/orders/{order_id}/refund-status` | 🔑 User Bearer | Refund phase + live provider status |
| `GET` | `/api/v1/orders` / `/api/v1/orders/{order_id}` | 🔑 User Bearer | Order list/detail — contains `payment_status` |
| `POST` | `/api/v1/webhooks/payment` | Signature header | Receives Razorpay events (`refund.processed`, `refund.failed`) |

---

## 3. Postman Test Data

### 3.1 Cancel a paid order → refund initiated/completed

**Endpoint:** `POST /api/v1/orders/{{ORDER_ID}}/cancel`
**Headers:**
```
Authorization: Bearer {{USER_ACCESS_TOKEN}}
Content-Type: application/json
```

**Request body:**
```json
{
  "reason": "Changed my mind"
}
```

**Response `200 OK` — LIVE mode (provider returned `pending`):**
```json
{
  "order_id": "b9c4f1f2-2a62-4f76-9b97-0d4f6672f3aa",
  "order_number": "ORD-8F2KJ1",
  "status": "cancelled",
  "message": "Order cancelled successfully",
  "refund": {
    "processed": true,
    "amount": 1168.50,
    "restocking_fee": 61.50,
    "fee_percentage": 5,
    "refund_id": "rfnd_2Xp7Qd99d3uRz2",
    "status": "pending",
    "payment_status": "refund_initiated",
    "message": "Refund of ₹1168.50 initiated successfully. It will reflect in your account within 5 business days."
  }
}
```

**Response `200 OK` — TEST / dummy mode (provider returned `processed`):**
```json
{
  "order_id": "b9c4f1f2-2a62-4f76-9b97-0d4f6672f3aa",
  "order_number": "ORD-8F2KJ1",
  "status": "cancelled",
  "message": "Order cancelled successfully",
  "refund": {
    "processed": true,
    "amount": 1168.50,
    "restocking_fee": 61.50,
    "fee_percentage": 5,
    "refund_id": "rfnd_2Xp7Qd99d3uRz2",
    "status": "processed",
    "payment_status": "refund_completed",
    "message": "Refund of ₹1168.50 initiated successfully. It will reflect in your account within 5 business days."
  }
}
```

---

## 4. Postman Test Data — Refund Webhooks

### 4.1 Check refund status

**Endpoint:** `GET /api/v1/orders/{{ORDER_ID}}/refund-status`
**Headers:**
```
Authorization: Bearer {{USER_ACCESS_TOKEN}}
```

**Response `200 OK`:**
```json
{
  "order_id": "b9c4f1f2-2a62-4f76-9b97-0d4f6672f3aa",
  "order_number": "ORD-8F2KJ1",
  "refund_id": "rfnd_2Xp7Qd99d3uRz2",
  "refund_amount": 1168.50,
  "restocking_fee": 61.50,
  "fee_percentage": 5,
  "payment_status": "refund_initiated",
  "status": "pending",
  "message": "Your refund of ₹1168.50 is being processed. It will be credited within 5 business days."
}
```

| Field | Meaning |
|-------|---------|
| `payment_status` | **Our stored user-facing phase** — `refund_initiated` / `refund_completed` / `refund_failed`. **Use this in the UI.** |
| `status` | Live provider status from Razorpay — `processed` / `pending` / `failed` |

---

### 4.2 Simulate webhook: `refund.processed`

This is what Razorpay fires one to five days later when the money actually lands.
For local testing the provider is `dummy`, so you can POST this directly:

**Endpoint:** `POST /api/v1/webhooks/payment`
**Headers (Razorpay mode only):**
```
X-Razorpay-Signature: {{SIGNATURE}}
Content-Type: application/json
```

**Request body (DUMMY mode — local testing):**
```json
{
  "event": "refund.processed",
  "refund": {
    "id": "rfnd_2Xp7Qd99d3uRz2",
    "status": "processed",
    "amount": 116850,
    "payment_id": "pay_3Yk8Re55e4sUz1"
  }
}
```

**Request body (RAZORPAY mode — exact payload Razorpay sends):**
```json
{
  "entity": "event",
  "account_id": "acc_1GlsZktlUytHrv",
  "event": "refund.processed",
  "contains": ["refund"],
  "payload": {
    "refund": {
      "entity": {
        "id": "rfnd_2Xp7Qd99d3uRz2",
        "payment_id": "pay_3Yk8Re55e4sUz1",
        "order_id": "order_9A2Ks55e4sUz1",
        "status": "processed",
        "amount": 116850,
        "currency": "INR",
        "created_at": 1724820300
      }
    }
  },
  "created_at": 1724820301
}
```

**Response `200 OK` (both modes):**
```json
{
  "status": "received",
  "event_type": "refund.processed"
}
```

**DB effect:** `orders.payment_status` → `refund_completed`, customer gets the
"Refund Completed ✅" email.

---

### 4.3 Simulate webhook: `refund.failed`

**Endpoint:** `POST /api/v1/webhooks/payment`

**Request body (DUMMY mode):**
```json
{
  "event": "refund.failed",
  "refund": {
    "id": "rfnd_2Xp7Qd99d3uRz2",
    "status": "failed",
    "error_description": "Insufficient funds in merchant account"
  }
}
```

**Request body (RAZORPAY mode):**
```json
{
  "entity": "event",
  "account_id": "acc_1GlsZktlUytHrv",
  "event": "refund.failed",
  "contains": ["refund"],
  "payload": {
    "refund": {
      "entity": {
        "id": "rfnd_2Xp7Qd99d3uRz2",
        "payment_id": "pay_3Yk8Re55e4sUz1",
        "status": "failed",
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Insufficient funds in merchant account",
        "amount": 116850,
        "currency": "INR"
      }
    }
  },
  "created_at": 1724820301
}
```

**Response `200 OK`:**
```json
{
  "status": "received",
  "event_type": "refund.failed"
}
```

**DB effect:** `orders.payment_status` → `refund_failed`, admin gets a console
`❌ REFUND FAILED ... manual intervention needed` alert + customer email.

> 💡 The webhook is **idempotent** — replaying `refund.processed` for an order
> that is already `refund_completed` is safe (no duplicate emails).

---

## 5. Frontend Dev Guide 👩‍💻

### 5.1 Status → UI mapping (single source of truth: `order.payment_status`)

| `payment_status` | Badge | Color | User message |
|------------------|-------|-------|--------------|
| `pending` / `paid` | — | — | No refund — show normal order status |
| `refund_initiated` | 🟡 **Refund Processing** | `yellow` | "Your refund is being processed. It will reach your account within 5 business days." |
| `refund_completed` | 🟢 **Refund Completed** | `green` | "Your refund has been completed ✅" |
| `refund_failed` | 🔴 **Refund Failed** | `red` | "Your refund failed. Please contact support." |
| `refunded` (legacy) | 🟢 **Refund Completed** | `green` | Treat as `refund_completed` |

### 5.2 Ready-to-use React component

```jsx
// src/components/RefundBadge.jsx
export function RefundBadge({ paymentStatus }) {
  const config = {
    refund_initiated:  { label: '⏳ Refund Processing', color: 'yellow' },
    refund_completed:  { label: '✅ Refund Completed',  color: 'green'  },
    refund_failed:     { label: '❌ Refund Failed',     color: 'red'    },
    refunded:          { label: '✅ Refund Completed',  color: 'green'  },  // legacy
  };
  const item = config[paymentStatus];
  if (!item) return null;             // paid / pending / cod_pending — no badge
  return <span className={`badge badge-${item.color}`}>{item.label}</span>;
}
```

```jsx
// src/pages/customer/Orders.jsx  (usage)
<td><RefundBadge paymentStatus={order.payment_status} /></td>
```

### 5.3 Display the refund message

```jsx
{order.payment_status === 'refund_initiated' && (
  <p className="text-yellow-600">
    Your refund is being processed. It will reach your account within 5 business days. 🕐
  </p>
)}
{order.payment_status === 'refund_completed' && (
  <p className="text-green-600">
    Your refund of ₹{order.refund_amount} has been completed ✅
  </p>
)}
{order.payment_status === 'refund_failed' && (
  <p className="text-red-600">
    Your refund failed. Please contact support@ourstore.com for assistance.
  </p>
)}
```

### 5.4 Where the fields come from

| Frontend needs | Endpoint | Field |
|----------------|----------|-------|
| Order list / detail badge | `GET /api/v1/orders` or `GET /api/v1/orders/{id}` | `payment_status`, `refund_amount`, `refund_id`, `restocking_fee` |
| Refund detail page | `GET /api/v1/orders/{id}/refund-status` | `payment_status` (phase), `status` (live), `message`, `refund_amount` |

> 🔁 **No polling needed if Razorpay webhooks are configured.** The backend flips
> `refund_initiated` → `refund_completed` when `refund.processed` arrives, and the
> frontend just reflects it on the next fetch/refresh. Optionally poll
> `/refund-status` every 60s while `payment_status === 'refund_initiated'`.

### 5.5 Razorpay dashboard configuration (for the backend dev)

- Add webhook URL: `https://<your-domain>/api/v1/webhooks/payment`
- Subscribe to events: `payment.captured`, `order.paid`, **`refund.processed`**, **`refund.failed`**
- Set webhook secret = `RAZORPAY_WEBHOOK_SECRET` from `.env`