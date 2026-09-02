# E-Commerce Backend — API Documentation

> **Handover document for Frontend Developers**
> Framework: FastAPI (Python 3.12) + SQLModel + PostgreSQL
> Last updated: 2026-09-02 — generated from source code (`app/api/v1/**`, `app/schemas/**`)

---

## Table of Contents

1. [Overview & Base URL](#1-overview--base-url)
2. [Authentication & Authorization](#2-authentication--authorization)
3. [General Conventions](#3-general-conventions)
4. [Error Handling](#4-error-handling)
5. [Auth Module — `/auth`](#5-auth-module--auth)
6. [Products — `/products`](#6-products--products)
7. [Product Images — `/products/{id}/images`](#7-product-images--productsproduct_idimages)
8. [Categories — `/categories`](#8-categories--categories)
9. [Cart — `/cart`](#9-cart--cart)
10. [Checkout — `/checkout`](#10-checkout--checkout)
11. [Addresses — `/addresses`](#11-addresses--addresses)
12. [Orders & Refunds — `/orders`](#12-orders--refunds--orders)
13. [Payments — `/payments`](#13-payments--payments)
14. [Payment Webhook — `/webhooks/payment`](#14-payment-webhook--webhooks_payment)
15. [Reviews — `/reviews`](#15-reviews--reviews)
16. [Wishlist — `/wishlist`](#16-wishlist--wishlist)
17. [Coupons — `/coupons`](#17-coupons--coupons)
18. [Email — `/email`](#18-email--email)
19. [Analytics — `/analytics`](#19-analytics--analytics)
20. [Chat — `/chat`](#20-chat--chat)
21. [Admin — `/admin/*`](#21-admin--admin)
22. [Enums & Status Values Reference](#22-enums--status-values-reference)
23. [Business Rules (Pricing / COD / Refunds)](#23-business-rules-pricing--cod--refunds)
24. [Typical Frontend Flows](#24-typical-frontend-flows)
25. [Endpoint Quick-Reference Table](#25-endpoint-quick-reference-table)

---

## 1. Overview & Base URL

This is a full e-commerce backend: auth (email + Google), catalog, cart (guest + user), checkout, online payments (Razorpay) + Cash-on-Delivery, orders with cancellation/refunds, reviews, wishlist, coupons, an AI customer-support chatbot (Google Gemini), analytics, and an admin suite.

| Item | Value |
|---|---|
| **Base URL (dev)** | `http://localhost:8000/api/v1` |
| **All paths below** | Relative to the base URL (prefix `/api/v1` already applied in code) |
| **Interactive docs** | `http://localhost:8000/docs` (Swagger UI — try calls there) |
| **ReDoc** | `http://localhost:8000/redoc` |
| **Health/root check** | `GET http://localhost:8000/` |
| **Content type** | `application/json` for every request & response (no file uploads in this API) |
| **CORS** | Configured server-side via `CORS_ORIGINS` env var (`*` in dev); `allow_credentials=true`, all methods/headers allowed |

Root endpoint response:

```json
GET /
{
  "message": "E-Commerce API",
  "environment": "development",
  "payment_provider": "razorpay"
}
```

`payment_provider` is `"razorpay"` in production config, `"dummy"` for local testing (payments auto-succeed).

---

## 2. Authentication & Authorization

### 2.1 Scheme — JWT Bearer

- Standard **OAuth2 Bearer** scheme. Send the access token in the header on every protected call:

```
Authorization: Bearer <access_token>
```

- Tokens are obtained from `POST /auth/login`, `POST /auth/refresh`, or `POST /auth/google` (all return a **TokenPair**).

**TokenPair response (used by login / refresh / google):**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "b1f0c3d4e5f6...a9(64-char random string)",
  "token_type": "bearer"
}
```

### 2.2 Token Lifecycle

| | Access Token | Refresh Token |
|---|---|---|
| Format | JWT (HS256) | Opaque random 64-char hex string (NOT a JWT) |
| Expiry | **15 minutes** | **30 days** |
| Payload | `{ "sub": "<email>", "role": "customer", "exp": …, "type": "access" }` | Stored server-side, revocable |
| Sent as | `Authorization: Bearer …` header | JSON body `{ "refresh_token": "…" }` on refresh/logout |
| Reuse | — | **Single-use**: every `POST /auth/refresh` **rotates** it — store the NEW one returned, discard the old |

**Frontend responsibilities:**

1. Store both tokens (localStorage / memory — your choice).
2. Attach the access token header to protected requests.
3. On any `401` response, call `POST /auth/refresh` once; if it succeeds, retry the original request and persist the new token pair; if it fails (401), log the user out.
4. On logout, call `POST /auth/logout` with the refresh token, then discard both tokens.

### 2.3 Roles (Authorization)

Role-protected endpoints return `403 Forbidden` with `{"detail": "Insufficient permissions"}` if the role is insufficient.

| Role | Can do |
|---|---|
| `customer` | Everything shopper-facing: products, cart, checkout, orders, addresses, reviews, wishlist |
| `staff` | + Create/update/delete **products, variants, product images** |
| `manager` | + **Categories, coupons, analytics, admin dashboard, admin orders, COD collection, test email** |
| `admin` | + **User management (list/role/status/delete), product export & bulk operations** |

New registrations are always `customer`. Only an admin can change roles (Admin → Users).

### 2.4 Guest (unauthenticated) behaviour

- Catalog browsing, categories, and reading product reviews are public.
- The **cart works for guests**. Guest carts are identified by a **Cart Session ID** — send either:
  - Header: `X-Cart-Session-ID: <any-unique-string-you-generate>` (recommended), **or**
  - Cookie: `cart_session_id=<value>` (backend never sets this cookie; the frontend may).
- Generate the value client-side (e.g. a UUID) and keep it stable for the guest session.
- Cart endpoints use *optional* auth: with a valid Bearer token you get the user cart; without one, the session-ID cart.

### 2.5 Unauthenticated error

```json
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer
{ "detail": "Could not validate credentials" }
```

Also returned when the token is expired, malformed, or the account was deactivated.

---

## 3. General Conventions

| Convention | Detail |
|---|---|
| **Request/response body** | Always JSON (UTF-8). No multipart/form-data anywhere. |
| **IDs** | UUIDv4 strings, e.g. `"3fa85f64-5717-4562-b3fc-2c963f66afa6"` |
| **Dates/times** | ISO 8601 UTC, e.g. `"2026-08-29T12:34:56.789012+00:00"` |
| **Money (important!)** | In Pydantic-schema responses (cart, orders, products, payments…) money fields are **JSON strings** — e.g. `"1499.00"` — because `Decimal` is serialized as a string to preserve precision. Some admin/analytics endpoints build raw dicts and return **numbers** instead. Each section states which. |
| **Pagination (query)** | `page` + `limit` (page starts at 1) or `skip` + `limit` (offset style) — documented per endpoint. |
| **Validation errors** | HTTP `422` with a `detail` **array** — see §4.2 |
| **Trailing slashes** | `GET /products/` (list) vs `GET /products/{slug}` are different routes — use paths exactly as documented |
| **Rate limiting** | `slowapi` is installed but **not enabled** — no rate-limit headers |

---

## 4. Error Handling

All errors share one envelope: a JSON object with a `detail` key.

### 4.1 Business errors (400 / 401 / 403 / 404 / 409…)

```json
HTTP/1.1 400 Bad Request
{ "detail": "Not enough stock for SHOE-42. Available: 3, Requested: 5" }
```

`detail` is always a **string** for errors raised inside handlers. Display it to the user directly.

### 4.2 Request-schema validation errors (422)

When body/query doesn't match the schema, FastAPI returns:

```json
HTTP/1.1 422 Unprocessable Entity
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "email"],
      "msg": "value is not a valid email address",
      "input": "not-an-email"
    }
  ]
}
```

`loc` points to the offending field (`["body","field"]` or `["query","param"]`). Map `loc[1]` to form fields for inline errors.

### 4.3 Unhandled server errors (500)

```json
HTTP/1.1 500 Internal Server Error
{ "detail": "Internal server error" }
```

CORS headers are always attached — even on 500s — so the browser shows the real status, not a CORS error.

### 4.4 Status codes used across the API

| Code | Meaning |
|---|---|
| 200 | OK (default) |
| 201 | Created (register, create product/category/address/order/coupon…) |
| 204 | No Content — **empty body** (logout, deletes) |
| 400 | Bad request / business rule violated (body `detail` explains) |
| 401 | Missing/invalid/expired token, bad credentials, invalid refresh token |
| 403 | Authenticated but role insufficient / resource not owned by you / account disabled |
| 404 | Resource not found |
| 409 | Conflict — duplicate slug/SKU (categories, variants) |
| 422 | Request body/query failed schema validation |
| 500 | Unhandled server error |

---

## 5. Auth Module — `/auth`

### 5.1 `POST /auth/register` — Create account 🔓 Public

**Request body** (`UserCreate`):

```json
{
  "email": "user@example.com",
  "username": "john_doe",
  "password": "min-8-chars",
  "full_name": "John Doe",
  "phone": "9876543210"
}
```

| Field | Type | Rules |
|---|---|---|
| `email` | string | valid email, unique |
| `username` | string | unique; only letters, numbers, underscore |
| `password` | string | **min 8 characters** |
| `full_name` | string? | optional |
| `phone` | string? | optional |

**Response `201`** (`UserRead`) — same shape as `GET /auth/me` below. New users get `role: "customer"`.

**Errors:** `400 Email already registered` · `400 Username already taken` · `422` validation

> A welcome email is sent automatically (if SendGrid is configured).

---

### 5.2 `POST /auth/login` — Email + password 🔓 Public

**Request body** (`UserLogin`):

```json
{ "email": "user@example.com", "password": "secret123" }
```

**Response `200`** → **TokenPair** (see §2.1).

**Errors:**
- `401 Incorrect email or password`
- `400 This account was created with Google. Please sign in with Google.` (Google-only account, no password set)
- `403 Account disabled`

---

### 5.3 `POST /auth/refresh` — Rotate tokens 🔓 Public

**Request body:**

```json
{ "refresh_token": "<current refresh token>" }
```

**Response `200`** → **new TokenPair** (both tokens are fresh; the old refresh token is now invalid).

**Errors:** `401 Invalid or expired refresh token`

---

### 5.4 `POST /auth/logout` — Revoke session 🔓 Public (token of that session)

**Request body:** same as refresh — `{ "refresh_token": "…" }`

**Response:** `204 No Content` (empty body). The refresh token is revoked server-side.

**Errors:** `401 Invalid or expired refresh token`

---

### 5.5 `GET /auth/me` — Current user 🔒 Bearer

**Response `200`** (`UserRead`):

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "email": "user@example.com",
  "username": "john_doe",
  "role": "customer",
  "full_name": "John Doe",
  "phone": "9876543210",
  "is_active": true,
  "email_verified": true,
  "auth_provider": "email",
  "created_at": "2026-08-29T10:00:00.000000+00:00",
  "updated_at": "2026-08-29T10:00:00.000000+00:00"
}
```

`auth_provider` is one of `"email" | "google" | "both"` — useful to decide whether to offer "set a password" UI to Google users.

**Errors:** `401` (see §2.5)

---

### 5.6 `PUT /auth/profile` — Update profile 🔒 Bearer

**Request body** (`UserUpdateProfile`) — all fields optional:

```json
{ "full_name": "John Doe Jr.", "phone": "9999999999", "username": "john_doe_2" }
```

**Response `200`** → `UserRead` (as above).

**Errors:** `400 Username already taken` · `422` invalid username characters

---

### 5.7 `POST /auth/google` — Sign in with Google 🔓 Public

Frontend gets a Google **ID token** (e.g. via Google Identity Services / "Sign in with Google" button), then exchanges it here.

**Request body** (`GoogleAuthRequest`):

```json
{ "id_token": "eyJhbGciOiJSUzI1NiIsImtpZCI6..." }
```

**Response `200`** → **TokenPair**. If the Google email doesn't exist yet, an account is auto-created (`auth_provider: "google"`); if it exists, the Google identity is linked to it.

**Errors:** `401 Invalid Google token or Google Auth not configured` · `403 Account disabled`

---

### 5.8 `POST /auth/set-password` — Google users add a password 🔒 Bearer

Only for users who have **no password yet** (Google-only).

**Request body** (`SetPasswordRequest`):

```json
{ "password": "min-8-chars" }
```

**Response `200`:**

```json
{ "message": "Password set successfully. You can now login with email/password." }
```

**Errors:** `400 You already have a password. Use 'change-password' instead.` · `400 You already have a password set.`

---

### 5.9 `POST /auth/forgot-password` — Request reset link 🔓 Public

**Request body:**

```json
{ "email": "user@example.com" }
```

**Response `200` (always, even if the email is unknown — don't reveal account existence):**

```json
{ "message": "If an account with this email exists, a reset link has been sent." }
```

> Backend emails a link of the form `{FRONTEND_URL}/reset-password?token=<token>` (token valid **1 hour**). Your reset page must read `token` from the URL and post it to the next endpoint.

---

### 5.10 `POST /auth/reset-password` — Set new password with token 🔓 Public

**Request body** (`ResetPasswordRequest`):

```json
{ "token": "<token-from-email-link>", "new_password": "min-8-chars" }
```

**Response `200`:**

```json
{ "message": "Password reset successfully. You can now login with your new password." }
```

**Errors:** `400 Invalid or expired reset token` · `404 User not found`

---

### 5.11 `POST /auth/change-password` — Change password (logged in) 🔒 Bearer

**Request body** (`ChangePasswordRequest`):

```json
{ "current_password": "old-pass", "new_password": "min-8-chars" }
```

**Response `200`:**

```json
{ "message": "Password changed successfully." }
```

**Errors:** `400 You don't have a password set. Use 'set-password' endpoint.` (Google-only user) · `401 Current password is incorrect`

---

## 6. Products — `/products`

### ProductRead — the product shape used everywhere

```json
{
  "id": "uuid",
  "name": "Classic White T-Shirt",
  "slug": "classic-white-t-shirt",
  "description": "100% cotton…",
  "category_id": "uuid | null",
  "price": "1499.00",
  "compare_at_price": "1999.00",
  "is_active": true,
  "created_by": "uuid | null",
  "created_at": "2026-08-01T10:00:00+00:00",
  "updated_at": "2026-08-20T10:00:00+00:00",
  "images": [
    { "id": "uuid", "product_id": "uuid", "url": "https://…", "alt_text": "front", "sort_order": 0, "created_at": "…" }
  ],
  "variants": [
    {
      "id": "uuid",
      "product_id": "uuid",
      "sku": "TSHIRT-WHT-M",
      "attributes": { "size": "M", "color": "White" },
      "price_override": "1299.00",
      "stock": 12,
      "created_at": "…",
      "effective_price": "1299.00",
      "discount_percentage": 35,
      "savings_amount": "700.00",
      "is_on_sale": true
    }
  ],
  "discount_percentage": 25,
  "savings_amount": "500.00",
  "is_on_sale": true,
  "average_rating": 4.6,
  "review_count": 12
}
```

> **Money = strings.** `price`, `compare_at_price`, `savings_amount`, `price_override`, `effective_price` are JSON strings. `discount_percentage`, `is_on_sale`, `average_rating` and `review_count` are **computed server-side** (pricing from the product/variants; `average_rating`/`review_count` aggregated from the reviews table) — use them for badges & rating chips; don't recompute.

### 6.1 `GET /products/` — List products 🔓 Public

**Query params:**

| Param | Type | Default | Notes |
|---|---|---|---|
| `search` | string? | — | 1–100 chars, searches name/description |
| `category_id` | UUID? | — | filter by category |
| `min_price` / `max_price` | number? | — | `≥ 0`; `min > max` → `400 min_price cannot be greater than max_price` |
| `sort` | enum | `newest` | one of `newest, oldest, price_asc, price_desc, name_asc, name_desc` |
| `page` | int | `1` | `≥ 1` |
| `limit` | int | `20` | 1–100 |

**Response `200`:** array of `ProductRead` (only **active** products).

> Note: this endpoint returns a plain array (no pagination envelope). The frontend knows more pages exist while a full page is returned.

### 6.2 `GET /products/{slug}` — Product detail 🔓 Public

**Response `200`:** single `ProductRead`.

**Errors:** `404 Product not found`

### 6.3 `POST /products/` — Create product 🔒 staff / manager / admin

**Request body** (`ProductCreate`):

```json
{
  "name": "Classic White T-Shirt",
  "slug": "classic-white-t-shirt",
  "description": "100% cotton",
  "category_id": "uuid | null",
  "price": "1499.00",
  "compare_at_price": "1999.00",
  "variants": [
    { "sku": "TSHIRT-WHT-M", "attributes": { "size": "M" }, "price_override": null, "stock": 10 }
  ]
}
```

Rules: `name` ≤ 150 chars, `slug` ≤ 180 chars (unique), `price > 0`, `compare_at_price > 0` optional, `variants` optional list. Variant: `sku` 1–100 chars unique, `attributes` free-form object, `price_override > 0` optional, `stock ≥ 0`.

**Response `201`:** `ProductRead`.

**Errors:** `409` duplicate SKU · `422` validation

### 6.4 `PUT /products/{product_id}` — Update product 🔒 staff / manager / admin

**Request body** (`ProductUpdate`) — all fields optional: `name`, `slug`, `description`, `category_id`, `price`, `compare_at_price`, `is_active`.

```json
{ "price": "1399.00", "is_active": false }
```

**Response `200`:** `ProductRead`. · **Errors:** `404` · `422`

### 6.5 `DELETE /products/{product_id}` — Delete product 🔒 staff / manager / admin

**Response:** `204 No Content`. · **Errors:** `404 Product not found`

### 6.6 `GET /products/{product_id}/variants` — List variants 🔓 Public

**Response `200`:** array of `ProductVariantRead` (see shape in §ProductRead above).

**Errors:** `404 Product not found`

### 6.7 `POST /products/{product_id}/variants` — Create variant 🔒 staff / manager / admin

**Request body** (`ProductVariantCreate`):

```json
{ "sku": "TSHIRT-WHT-L", "attributes": { "size": "L" }, "price_override": "1399.00", "stock": 5 }
```

**Response `201`:** `ProductVariantRead`. · **Errors:** `404 Product not found` · `409 Variant with this SKU already exists`

### 6.8 `PUT /products/{product_id}/variants/{variant_id}` — Update variant 🔒 staff / manager / admin

**Request body** (`ProductVariantUpdate`) — all optional: `sku`, `attributes`, `price_override`, `stock`.

**Response `200`:** `ProductVariantRead`. · **Errors:** `404` (product / variant / not belonging) · `409` duplicate SKU

### 6.9 `DELETE /products/{product_id}/variants/{variant_id}` — Delete variant 🔒 staff / manager / admin

**Response:** `204 No Content`. · **Errors:** `404`

---

## 7. Product Images — `/products/{product_id}/images`

Image records store **URLs** — there is no file upload; host images on CDN/S3 yourself.

### 7.1 `GET /products/{product_id}/images` 🔓 Public

**Response `200`:**

```json
[
  { "id": "uuid", "product_id": "uuid", "url": "https://cdn…/1.jpg", "alt_text": "front", "sort_order": 0, "created_at": "…" }
]
```

**Errors:** `404 Product not found`

### 7.2 `POST /products/{product_id}/images` 🔒 staff / manager / admin

**Request body** (`ProductImageCreate`):

```json
{ "url": "https://cdn…/1.jpg", "alt_text": "front view", "sort_order": 0 }
```

`url` required ≤ 500 chars; `alt_text` ≤ 255 optional; `sort_order ≥ 0` default 0.

**Response `201`:** `ProductImageRead`. · **Errors:** `404` · `400` (repo validation)

### 7.3 `PUT /products/{product_id}/images/{image_id}` 🔒 staff / manager / admin

**Request body** (`ProductImageUpdate`) — all optional: `url`, `alt_text`, `sort_order`.

**Response `200`:** `ProductImageRead`. · **Errors:** `404 Image not found` / `404 Image does not belong to this product`

### 7.4 `DELETE /products/{product_id}/images/{image_id}` 🔒 staff / manager / admin

**Response:** `204 No Content`. · **Errors:** `404`

### 7.5 `POST /products/{product_id}/images/reorder` 🔒 staff / manager / admin

⚠️ Takes image IDs as **repeated query params**, not a JSON body:

```
POST /products/{id}/images/reorder?image_ids=<uuid1>&image_ids=<uuid2>&image_ids=<uuid3>
```

Order of the params = new display order. **Response `200`:** reordered array of `ProductImageRead`.

---

## 8. Categories — `/categories`

**CategoryRead shape:**

```json
{ "id": "uuid", "name": "T-Shirts", "slug": "t-shirts", "parent_id": null, "created_at": "…" }
```

| Endpoint | Auth | Body / Query | Response |
|---|---|---|---|
| `GET /categories` | 🔓 Public | `?skip=0&limit=100` | `200` array of `CategoryRead` |
| `GET /categories/{category_id}` | 🔓 Public | — | `200` `CategoryRead` / `404 Category not found` |
| `POST /categories` | 🔒 manager/admin | `{ "name": "T-Shirts", "slug": "t-shirts", "parent_id": null }` (`name` ≤100, `slug` ≤120) | `201` `CategoryRead` / `409 Category slug already exists` |
| `PUT /categories/{category_id}` | 🔒 manager/admin | same fields, all optional | `200` / `404` / `409` |
| `DELETE /categories/{category_id}` | 🔒 manager/admin | — | `204` / `404` |

---

## 9. Cart — `/cart`

Cart works **with or without login** (see §2.4). Every cart endpoint returns the full `CartRead` object, so the UI can re-render the whole cart from one call.

**CartRead shape (money = strings):**

```json
{
  "id": "cart-uuid",
  "items": [
    {
      "id": "cart-item-uuid",
      "variant_id": "uuid",
      "quantity": 2,
      "price_at_add": "1299.00",
      "created_at": "…",
      "variant_sku": "TSHIRT-WHT-M",
      "variant_attributes": { "size": "M", "color": "White" },
      "product_name": "Classic White T-Shirt",
      "product_slug": "classic-white-t-shirt",
      "product_image": "https://cdn…/1.jpg"
    }
  ],
  "subtotal": "2598.00",
  "coupon_code": "SAVE10",
  "discount_total": "259.80",
  "tax_total": "420.89",
  "shipping_total": "0.00",
  "total": "2759.09",
  "item_count": 2
}
```

Totals rules: `subtotal` = Σ(price_at_add × qty) · tax = **18% GST** on (subtotal − discount) · shipping = **free ≥ ₹1000** else **₹50** · `total` = subtotal − discount + tax + shipping (see §23).

### 9.1 `GET /cart` — Get cart 🍪/🔒 optional auth

Guests: send `X-Cart-Session-ID` header. **Response `200`:** `CartRead` (created empty if none exists yet).

### 9.2 `POST /cart/items` — Add item 🍪/🔒 optional auth — `201`

**Request body** (`AddToCartRequest`):

```json
{ "variant_id": "uuid", "quantity": 2 }
```

`quantity` 1–999. Adding the same variant again **increases** the quantity.

**Response `201`:** `CartRead`. · **Errors:** `400` (e.g. insufficient stock — `detail` is user-friendly)

### 9.3 `PUT /cart/items/{item_id}` — Update quantity 🍪/🔒 optional auth

**Request body:** `{ "quantity": 3 }` (1–999)

**Response `200`:** `CartRead`. · **Errors:** `404 Item not found` · `403 Not authorized` (item belongs to another cart) · `400` stock/quantity error

### 9.4 `DELETE /cart/items/{item_id}` — Remove item 🍪/🔒 optional auth

**Response `200`:** `CartRead` (without the item). · **Errors:** `404` · `403`

### 9.5 `DELETE /cart` — Clear cart 🍪/🔒 optional auth

**Response `200`:** `CartRead` with empty `items` and zeroed totals.

### 9.6 `POST /cart/coupon` — Apply coupon 🍪/🔒 optional auth

**Request body** (`ApplyCouponRequest`):

```json
{ "coupon_code": "SAVE10" }
```

**Response `200`:** `CartRead` with `coupon_code`, `discount_total`, `tax_total`, `total` recomputed.

**Errors:** `400` — user-friendly messages like "Coupon not found", "Coupon has expired", "Minimum order value not met", "Coupon usage limit reached" (display `detail` directly).

### 9.7 `DELETE /cart/coupon` — Remove coupon 🍪/🔒 optional auth

**Response `200`:** `CartRead` without discount.

---

## 10. Checkout — `/checkout`

### 10.1 `POST /checkout` — Convert cart to order 🔒 Bearer

Creates the order from the logged-in user's cart, validates stock, applies the cart coupon, calculates totals and **clears the cart**. Requires at least one saved address.

**Request body** (`CheckoutRequest`):

```json
{
  "shipping_address_id": "uuid",
  "billing_address_id": "uuid | null",
  "payment_method": "online"
}
```

| Field | Required | Notes |
|---|---|---|
| `shipping_address_id` | ✅ | must be an address owned by the user |
| `billing_address_id` | — | optional; **defaults to shipping address** if omitted |
| `payment_method` | — | `"cod"` or `"online"` (default `"online"`). Legacy values `card/upi/netbanking/wallet/emi` are silently coerced to `"online"` for backward compatibility. |

**Response `201`** (`OrderRead` — checkout variant, no nested address objects):

```json
{
  "id": "order-uuid",
  "order_number": "ORD-20260829-4821",
  "user_id": "uuid",
  "subtotal": "2598.00",
  "discount_total": "259.80",
  "tax_total": "420.89",
  "shipping_total": "0.00",
  "cod_fee": "0.00",
  "grand_total": "2759.09",
  "status": "pending",
  "payment_status": "pending",
  "payment_method": "online",
  "placed_at": "2026-08-29T12:00:00+00:00",
  "shipped_at": null,
  "delivered_at": null
}
```

- `payment_method: "online"` → order created with `status: "pending"`, `payment_status: "pending"` → **continue to Payments flow (§13)**.
- `payment_method: "cod"` → order created with `status: "confirmed"`, `payment_status: "cod_pending"`; a flat **₹50 COD fee** is added to `grand_total` (COD allowed only for grand totals ₹0–₹10000, else `400`). Fee/limits come from the `COD_FEE` / `COD_MIN_ORDER_VALUE` / `COD_MAX_ORDER_VALUE` settings and are exposed to clients via **§10.2**.

**Errors:**
- `400 Invalid shipping address` / `400 Invalid billing address`
- `400 Cart is empty`
- `400` stock problems, joined by `;` — e.g. `Not enough stock for TSHIRT-WHT-M. Available: 3, Requested: 5`
- `400` coupon problems
- `400 Cash on Delivery is available only for orders of ₹0 or more` / `…up to ₹10000. Please pay online.`
- `401` not logged in · `422` validation

### 10.2 `GET /checkout/config` — Checkout pricing configuration (public)

Display-only pricing rules for the storefront so the frontend never hardcodes business rules (COD fee, COD limits, shipping threshold, tax rate). **The server remains the single source of truth** — `POST /checkout` always recomputes fees/limits from the same settings, so client values are cosmetic only.

**Response `200`** (`CheckoutConfigResponse`):

```json
{
  "cod_fee": 50.0,
  "cod_min_order_value": 0.0,
  "cod_max_order_value": 10000.0,
  "free_shipping_threshold": 1000.0,
  "shipping_cost": 50.0,
  "tax_rate": 0.18
}
```

No auth required (nothing sensitive — mirrors non-secret settings). In production you can add `Cache-Control: public, max-age=60` (or an ETag) since values change rarely.

---

## 11. Addresses — `/addresses`

All endpoints 🔒 Bearer. Users only ever see/modify **their own** addresses.

**AddressRead shape:**

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "label": "Home",
  "line1": "12 MG Road",
  "line2": "Near Metro",
  "city": "Bengaluru",
  "state": "Karnataka",
  "postal_code": "560001",
  "country": "India",
  "is_default": true,
  "created_at": "…"
}
```

### 11.1 `GET /addresses` — List my addresses
**Response `200`:** array of `AddressRead`.

### 11.2 `POST /addresses` — Create address — `201`

**Request body** (`AddressCreate`):

```json
{
  "label": "Home",
  "line1": "12 MG Road",
  "line2": "Near Metro",
  "city": "Bengaluru",
  "state": "Karnataka",
  "postal_code": "560001",
  "country": "India",
  "is_default": false
}
```

`line1`, `city`, `state`, `postal_code` required; `country` defaults to `"India"`; `label`, `line2` optional.

### 11.3 `PUT /addresses/{address_id}` — Update address

**Request body** (`AddressUpdate`) — all optional (same fields as create).
**Response `200`:** `AddressRead`. · **Errors:** `404 Address not found` · `403 Not authorized`

### 11.4 `DELETE /addresses/{address_id}` — Delete address — `204`

**Errors:** `404` · `403` · `400` (address is used by an order and cannot be deleted — `detail` explains)

### 11.5 `POST /addresses/default/{address_id}` — Set default address

**Response `200`:** the address with `is_default: true` (any previous default is unset).
**Errors:** `404` · `403`

---

## 12. Orders & Refunds — `/orders`

All endpoints 🔒 Bearer. Users only see **their own** orders.

**OrderRead shape (full — used by `GET /orders`, `GET /orders/{id}`, `GET /orders/number/{n}`; money = strings):**

```json
{
  "id": "order-uuid",
  "order_number": "ORD-20260829-4821",
  "user_id": "uuid",
  "shipping_address_id": "uuid",
  "billing_address_id": "uuid",
  "user": { "id": "uuid", "full_name": "John Doe", "email": "…", "phone": "…" },
  "shipping_address": {
    "id": "uuid", "label": "Home", "line1": "…", "line2": "…", "city": "…",
    "state": "…", "postal_code": "…", "country": "…", "is_default": true,
    "full_name": "John Doe", "phone": "…"
  },
  "billing_address": { "...same as shipping_address..." },
  "subtotal": "2598.00",
  "discount_total": "259.80",
  "tax_total": "420.89",
  "shipping_total": "0.00",
  "grand_total": "2759.09",
  "status": "confirmed",
  "payment_status": "paid",
  "payment_method": "online",
  "coupon_code": "SAVE10",
  "cancellation_reason": null,
  "cancelled_at": null,
  "refund_amount": "0.00",
  "refund_id": null,
  "refund_reason": null,
  "restocking_fee": "0.00",
  "refunded_at": null,
  "placed_at": "…",
  "updated_at": "…",
  "shipped_at": null,
  "delivered_at": null,
  "items": [
    {
      "id": "item-uuid",
      "product_name": "Classic White T-Shirt",
      "variant_sku": "TSHIRT-WHT-M",
      "variant_attributes": { "size": "M" },
      "quantity": 2,
      "unit_price": "1299.00",
      "line_total": "2598.00",
      "created_at": "…"
    }
  ]
}
```

> **Note:** `cod_fee` is present on the checkout response but not in this list schema; `restocking_fee_percentage` (float, e.g. 5.0) is returned inside refund responses only.

### 12.1 `GET /orders` — My orders
Query: `?skip=0&limit=20`. **Response `200`:** array of `OrderRead`.

### 12.2 `GET /orders/{order_id}` — Order detail
**Response `200`:** `OrderRead`. · **Errors:** `404 Order not found` · `403 Not authorized`

### 12.3 `GET /orders/number/{order_number}` — Order by number (e.g. `ORD-…`)
**Response `200`:** `OrderRead`. · **Errors:** `404` · `403`

### 12.4 `POST /orders/{order_id}/cancel` — Cancel order 🔒 Bearer

Allowed while status is `pending`, `confirmed` or `processing`. Stock is restored. COD orders are simply cancelled; paid online orders get a Razorpay refund minus a **restocking fee** (0% pending / 5% confirmed / 15% processing — see §23).

**Request body** (`CancelOrderRequest`) — optional:

```json
{ "reason": "Changed my mind" }
```

**Response `200`** (`CancelOrderResponse`):

```json
{
  "order_id": "uuid",
  "order_number": "ORD-20260829-4821",
  "status": "cancelled",
  "message": "Order cancelled successfully",
  "refund": {
    "processed": true,
    "amount": "2621.14",
    "restocking_fee": "137.96",
    "fee_percentage": "5.00",
    "refund_id": "rfnd_XXXXXXXX",
    "status": "processed",
    "message": "Refund of ₹2621.14 initiated (5.0% restocking fee deducted). Credited within 5 business days."
  }
}
```

For COD / unpaid orders `refund.processed` is `false` with `amount: "0.00"`.

**Errors:**
- `400 Order has already been cancelled` / `400 Order has already been refunded`
- `400 Order cannot be cancelled. Current status: shipped` (also for `delivered`)
- `404 Order not found` · `403 Not authorized`

### 12.5 `GET /orders/{order_id}/refund-status` — Refund status 🔒 Bearer

**Response `200`** (`RefundStatusResponse`):

```json
{
  "order_id": "uuid",
  "order_number": "ORD-20260829-4821",
  "refund_id": "rfnd_XXXXXXXX",
  "refund_amount": "2621.14",
  "restocking_fee": "137.96",
  "fee_percentage": "5.00",
  "payment_status": "refund_completed",
  "status": "processed",
  "message": "Your refund of ₹2621.14 has been completed and credited to your account ✅"
}
```

- `payment_status` — stored phase: `refund_initiated | refund_completed | refund_failed`
- `status` — live provider status: `processed | pending | failed | unknown`
- `message` — **ready-to-display sentence**, use it directly.

**Errors:** `404 Order not found` / `404 No refund found for this order` · `403`

---

## 13. Payments — `/payments`

Online payment flow (Razorpay). With `PAYMENT_PROVIDER=dummy` everything auto-succeeds for local testing (`is_dummy: true`).

### 13.1 `POST /payments/create-intent` 🔒 Bearer

Call this after `POST /checkout` for `payment_method: "online"` orders.

**Request body** (`PaymentCreateRequest`):

```json
{ "order_id": "order-uuid", "payment_method": "online" }
```

(`payment_method` kept for compatibility; the actual instrument is chosen inside Razorpay's modal.)

**Response `200`** (`PaymentIntentResponse`):

```json
{
  "client_secret": "order_Nxxxxxxxxxxx",
  "payment_intent_id": "order_Nxxxxxxxxxxx",
  "order_id": "order-uuid",
  "amount": "2759.09",
  "currency": "INR",
  "is_dummy": false
}
```

- `amount` is in **rupees as a string** (Razorpay modal needs paise: `Math.round(amount * 100)`).
- **Razorpay mode:** `payment_intent_id` / `client_secret` = the Razorpay `order_*` id → open Razorpay Checkout with `key`, `amount` (paise), `currency: "INR"`, `order_id: payment_intent_id`.
- **Dummy mode:** `is_dummy: true`, `payment_intent_id = dummy_pay_xxx` → just call `/payments/confirm` directly.

**Errors:** `404 Order not found` · `403 Not authorized` · `400 This is a Cash on Delivery order. Payment will be collected on delivery.`

### 13.2 `POST /payments/confirm` 🔒 Bearer

Confirm/finalize the payment after the modal completes (or immediately in dummy mode).

**Request body** (`PaymentConfirmRequest`):

```json
{ "payment_intent_id": "order_Nxxxxxxxxxxx", "payment_method_id": null }
```

**Response `200`** (`PaymentRead`):

```json
{
  "id": "payment-uuid",
  "order_id": "order-uuid",
  "provider": "razorpay",
  "provider_payment_id": "order_Nxxxxxxxxxxx",
  "amount": "2759.09",
  "currency": "INR",
  "status": "succeeded",
  "payment_method": "upi",
  "last_four": null,
  "payment_metadata": { "...provider data..." },
  "created_at": "…",
  "paid_at": "2026-08-29T12:05:00+00:00",
  "refunded_at": null
}
```

On success the order flips to `status: "confirmed"`, `payment_status: "paid"`, and the customer receives a confirmation email.

**Errors:** `404 Payment not found` · `404 Order not found` · `403 Not authorized` · `400 Payment failed` · `400 Cash on Delivery orders cannot be confirmed online…`

---

## 14. Payment Webhook — `/webhooks/payment`

`POST /webhooks/payment` — **for Razorpay's servers only, not the frontend.** No Bearer auth; secured by HMAC-SHA256 signature (`X-Razorpay-Signature` header) verified against `RAZORPAY_WEBHOOK_SECRET`. Handles `payment.captured`, `order.paid`, `refund.processed`, `refund.failed`; other events are acknowledged with 200 and ignored. In `dummy` mode you can POST raw JSON (`{"event": "payment.succeeded", "payment_intent_id": "…"}`) to simulate events. Do not call this from the frontend.

---

## 15. Reviews — `/reviews`

**ReviewRead shape:**

```json
{
  "id": "uuid",
  "product_id": "uuid",
  "user_id": "uuid",
  "order_id": "uuid",            // the verified-purchase order this review is attached to
  "rating": 4,
  "title": "Great fit",
  "comment": "Fabric quality is excellent.",
  "is_verified_purchase": true,
  "created_at": "…",
  "updated_at": "…",
  "user_full_name": "John Doe"
}
```

| Endpoint | Auth | Details |
|---|---|---|
| `POST /reviews/{product_id}` | 🔒 Bearer | Body: `{ "rating": 1–5 (required), "title": "…?", "comment": "…?" }` → `200 ReviewRead`. **Verified-purchase rule:** only a buyer whose order for this product was paid & received can review → `403 You can only review products you have purchased and received`. One review per user per product → `400 You have already reviewed this product`; `404 Product not found` |
| `GET /reviews/products/{product_id}` | 🔓 Public | `?skip=0&limit=20` → array of `ReviewRead`; `404 Product not found` |
| `GET /reviews/product/{product_id}/rating` | 🔓 Public | → `{ "average_rating": 4.3 }` (`0.0` when unrated); `404` |
| `GET /reviews/my-reviews` | 🔒 Bearer | `?skip=0&limit=20` → array of `ReviewRead` |
| `PUT /reviews/{review_id}` | 🔒 Bearer (owner) | Body: any of `rating`/`title`/`comment` → `200 ReviewRead`; `404` · `403 Not authorized` |
| `DELETE /reviews/{review_id}` | 🔒 Bearer (owner) | → `204`; `404` · `403` |

---

## 16. Wishlist — `/wishlist`

All 🔒 Bearer (per-user).

**WishlistItemRead shape:**

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "product_id": "uuid",
  "created_at": "…",
  "product_name": "Classic White T-Shirt",
  "product_slug": "classic-white-t-shirt",
  "product_price": "1499.00",
  "product_image": "https://cdn…/1.jpg"
}
```

| Endpoint | Details |
|---|---|
| `GET /wishlist` | `?skip=0&limit=20` → `{ "items": [WishlistItemRead…], "total": 3 }` |
| `POST /wishlist/{product_id}` | Add product → `201 WishlistItemRead`; `404 Product not found` |
| `DELETE /wishlist/{product_id}` | Remove by product id → `204`; `404 Item not found in wishlist` |
| `GET /wishlist/check/{product_id}` | → `{ "in_wishlist": true }` |

---

## 17. Coupons — `/coupons`

### 17.1 `POST /coupons/validate` — Check a code 🔓 Public

**Request body:** `{ "code": "SAVE10" }`

**Response `200`** (`CouponValidateResponse`):

```json
{ "valid": true, "message": "Coupon is valid", "discount_type": "percentage", "value": "10.00", "min_order_value": "500.00" }
```

Unknown codes return `200` with `{ "valid": false, "message": "Coupon not found" }` (never an HTTP error).

**CouponRead shape** (admin endpoints; money = strings):

```json
{
  "id": "uuid", "code": "SAVE10", "discount_type": "percentage", "value": "10.00",
  "min_order_value": "500.00", "max_uses": 100, "max_uses_per_user": 1, "times_used": 12,
  "valid_from": "…", "valid_until": "2026-12-31T23:59:59+00:00", "is_active": true,
  "created_by": "uuid", "created_at": "…", "updated_at": "…"
}
```

`discount_type`: `"percentage"` (value = % off) or `"fixed"` (value = ₹ off).

### Admin endpoints — 🔒 manager/admin

| Endpoint | Body / Query | Response |
|---|---|---|
| `GET /coupons` | `?is_active=true&skip=0&limit=100` | array of `CouponRead` |
| `GET /coupons/{coupon_id}` | — | `CouponRead` / `404` |
| `POST /coupons` | `CouponCreate` below | `201 CouponRead` / `400 Coupon code already exists` |
| `PUT /coupons/{coupon_id}` | `CouponUpdate` (all optional) | `200` / `404` / `400` duplicate code |
| `DELETE /coupons/{coupon_id}` | — | `204` / `404` |
| `POST /coupons/generate?length=8` | query `length` (default 8) | `{ "code": "X7K2P9AB" }` |

**`CouponCreate`:**

```json
{
  "code": "SAVE10",
  "discount_type": "percentage",
  "value": "10.00",
  "min_order_value": "500.00",
  "max_uses": 100,
  "max_uses_per_user": 1,
  "valid_from": "2026-08-01T00:00:00Z",
  "valid_until": "2026-12-31T23:59:59Z",
  "is_active": true
}
```

`code` 3–50 chars; `value > 0`; `valid_until` **required**.

---

## 18. Email — `/email`

### 18.1 `POST /email/test` 🔒 manager/admin

**Request body:** `{ "email": "someone@example.com" }`
**Response `200`:** `{ "message": "Test email sent successfully" }` · **Errors:** `400 Failed to send email`

Transactional emails (welcome, order confirmation, shipped, delivered, cancelled, refunded, password reset) are sent automatically by the backend — the frontend never triggers them.

---

## 19. Analytics — `/analytics`

All 🔒 **manager/admin**. Dates are `YYYY-MM-DD`.

| Endpoint | Query | Response `200` |
|---|---|---|
| `GET /analytics/dashboard` | — | `{ "today": {...}, "this_week": {...}, "this_month": {...}, "total": {...} }` — each period dict contains revenue/order metrics (numbers) |
| `GET /analytics/sales` | `from_date` ✅, `to_date` ✅, `group_by=day\|week\|month` | `{ "summary": { "total_sales": 0, "order_count": 0, "average_order_value": 0 }, "period_data": [ { "period": "2026-08-29", "total_sales": 0, "order_count": 0, "average_order_value": 0 } ] }` |
| `GET /analytics/top-products` | `limit=10` (1–100), `from_date?`, `to_date?` | `[ { "product_id": "uuid", "product_name": "…", "product_slug": "…", "total_quantity_sold": 0, "total_revenue": 0, "average_price": 0 } ]` |
| `GET /analytics/orders` | `from_date?`, `to_date?` | `{ "total_orders": 0, "by_status": [ { "status": "pending", "count": 0, "revenue": 0 } ] }` |
| `GET /analytics/revenue` | `from_date` ✅, `to_date` ✅, `group_by=day\|week\|month` | `{ "period_data": [ { "period": "…", "revenue": 0, "discounts": 0, "tax": 0, "shipping": 0, "net_revenue": 0 } ] }` |
| `GET /analytics/customers` | `from_date?`, `to_date?` | `{ "total_customers": 0, "active_customers": 0, "new_customers": 0, "repeat_customers": 0, "customer_retention_rate": 0.0 }` |

**Errors:** `400 from_date cannot be greater than to_date` (sales/revenue) · `403` insufficient role

> Numbers here are JSON **numbers** (floats), not strings.

---

## 20. Chat — `/chat`

AI customer-support chatbot powered by **Google Gemini** (`GEMINI_API_KEY`; model `gemini-3.5-flash`) with a fixed e-commerce system prompt (answers stay short — 2–3 sentences; it offers to connect the user with a human agent when it doesn't know something). Currently **public (no auth)** and **stateless** — no conversation history is stored server-side.

| Endpoint | Auth | Body / Query | Response `200` |
|---|---|---|---|
| `POST /chat` | 🔓 Public | `{ "message": "Do you ship internationally?" }` | `{ "reply": "…" }` |
| `GET /chat/history` | 🔓 Public | — | `[]` (stateless placeholder — nothing persisted yet) |
| `DELETE /chat/history` | 🔓 Public | — | `{ "message": "History cleared" }` |

`message` is trimmed; an empty message returns `{ "reply": "Please type a message 🙂" }`. If the Gemini call fails (quota / network / no API key) the API still answers `200` with a graceful fallback: `{ "reply": "Sorry, I'm having trouble right now. Please try again." }`.

---

## 21. Admin — `/admin/*`

### 21.1 Dashboard — `GET /admin/dashboard` 🔒 manager/admin

**Response `200`:**

```json
{
  "users":     { "total_users": 0, "active_users": 0, "inactive_users": 0, "admin_users": 0, "staff_users": 0, "manager_users": 0, "customer_users": 0, "google_users": 0, "email_users": 0, "both_users": 0 },
  "orders":    { "total_orders": 0, "pending_orders": 0, "confirmed_orders": 0, "processing_orders": 0, "shipped_orders": 0, "delivered_orders": 0, "cancelled_orders": 0, "refunded_orders": 0, "total_revenue": 0.0 },
  "revenue":   { "today": {...}, "this_week": {...}, "this_month": {...}, "total": {...} },
  "total_products": 0,
  "recent_orders": [ { "...order fields as in §21.2 items..." } ],
  "timestamp": "2026-08-29T12:00:00.000000"
}
```

### 21.2 Admin Orders 🔒 manager/admin — `/admin/orders`

**`GET /admin/orders`** — query: `page=1`, `limit=20` (≤100), `status` (order status string), `search` (order number / customer), `from_date`, `to_date` (`YYYY-MM-DD`).

**Response `200`** (⚠️ money & timestamps here are plain JSON — **numbers** and ISO strings):

```json
{
  "orders": [
    {
      "id": "uuid", "order_number": "ORD-…", "user_id": "uuid",
      "user": { "id": "uuid", "full_name": "…", "email": "…", "phone": "…" },
      "shipping_address": { "id": "uuid", "label": "…", "line1": "…", "line2": "…", "city": "…", "state": "…", "postal_code": "…", "country": "…", "is_default": false, "full_name": "…", "phone": "…" },
      "billing_address": { "…same shape…" },
      "shipping_address_id": "uuid", "billing_address_id": "uuid",
      "subtotal": 2598.0, "discount_total": 259.8, "tax_total": 420.89, "shipping_total": 0.0, "grand_total": 2759.09,
      "status": "confirmed", "payment_status": "paid", "coupon_code": "SAVE10",
      "cancellation_reason": null, "cancelled_at": null,
      "placed_at": "…", "updated_at": "…", "shipped_at": null, "delivered_at": null,
      "items": [ { "id": "uuid", "product_name": "…", "variant_sku": "…", "variant_attributes": {}, "quantity": 2, "unit_price": 1299.0, "line_total": 2598.0, "created_at": "…" } ]
    }
  ],
  "pagination": { "page": 1, "limit": 20, "total": 42, "total_pages": 3 }
}
```

**`GET /admin/orders/stats`** → order statistics dict (counts by status + revenue).

**`GET /admin/orders/{order_id}`** → single order dict (same shape as items above).

**`PUT /admin/orders/{order_id}/status`** — update lifecycle status:

```json
{ "status": "shipped" }
```

`status` ∈ `pending | confirmed | processing | shipped | delivered | cancelled | refunded`. **Response `200`:** `OrderRead` (§12 shape, money = strings). Shipped/delivered/cancelled/refunded transitions trigger customer emails automatically.

**Business rules:**

- **Cancelling** (`status=cancelled`) from the admin panel behaves like the user-facing cancel (`POST /orders/{id}/cancel`): it is allowed only from `pending | confirmed | processing` and **automatically restores variant stock** (`variant.stock += item.quantity` for every order item, same DB transaction).
- **Terminal states:** an order already `cancelled` or `refunded` cannot have its status changed — **`400 Order is already cancelled/refunded — its status cannot be changed`** (this also prevents a double stock restore via a cancelled → active → cancelled cycle).
- **`400 Order cannot be cancelled. Current status: shipped|delivered`** when trying to cancel an order that has shipped.
- ⚠️ Setting `refunded` here only changes the label — no money moves. Use the user-cancel flow (`POST /orders/{id}/cancel`) for real Razorpay refunds.

### 21.3 Admin Users 🔒 **admin** — `/admin/users`

**`AdminUserRead` shape** (same fields as `UserRead` in §5.5):

```json
{ "id": "uuid", "email": "…", "username": "…", "role": "customer", "full_name": "…", "phone": "…", "is_active": true, "email_verified": true, "auth_provider": "email", "created_at": "…", "updated_at": "…" }
```

| Endpoint | Query / Body | Response |
|---|---|---|
| `GET /admin/users` | `?page=1&limit=20&search=&role=customer&is_active=true` | `{ "users": [AdminUserRead…], "total": 0, "page": 1, "limit": 20, "total_pages": 0 }` |
| `GET /admin/users/stats` | — | `{ "total_users": 0, "active_users": 0, "inactive_users": 0, "admin_users": 0, "staff_users": 0, "manager_users": 0, "customer_users": 0, "google_users": 0, "email_users": 0, "both_users": 0 }` |
| `GET /admin/users/{user_id}` | — | `AdminUserRead` / `404 User not found` |
| `PUT /admin/users/{user_id}/role` | `{ "role": "staff" }` (also accepts `full_name`, `phone`) | `AdminUserRead` / `400 Cannot change your own role` |
| `PUT /admin/users/{user_id}/status` | `{ "is_active": false }` | `AdminUserRead` / `400 Cannot deactivate your own account` |
| `DELETE /admin/users/{user_id}` | — | `204` / `400 Cannot delete your own account` / `400 Cannot delete user. They have N address(es)/order(s)…` |

`role` ∈ `customer | staff | manager | admin`.

### 21.4 Admin Products 🔒 — `/admin/products`

| Endpoint | Auth | Query / Body | Response |
|---|---|---|---|
| `GET /admin/products` | manager/admin | `?page=1&limit=20&search=&is_active=true` | `{ "products": [ProductRead…], "pagination": { "page", "limit", "total", "total_pages" } }` |
| `GET /admin/products/export` | **admin** | `?format=json` | `{ "format": "json", "count": 0, "data": [ { product incl. images & variants (stringified prices) } ] }` |
| `GET /admin/products/{product_id}` | manager/admin | — | `ProductRead` / `404` |
| `POST /admin/products/bulk-delete` | **admin** | ⚠️ repeated **query params**: `?product_ids=<uuid>&product_ids=<uuid>` | `{ "deleted_count": 2, "message": "Successfully deleted 2 products" }` |
| `POST /admin/products/bulk-update-status` | **admin** | ⚠️ repeated **query params**: `?product_ids=<uuid>&is_active=true` | `{ "updated_count": 2, "message": "Successfully updated 2 products to active" }` |

Both bulk endpoints return `400 No product IDs provided` when the list is empty.

### 21.5 Admin COD (Cash on Delivery) 🔒 manager/admin — `/admin/cod`

COD lifecycle: checkout (`payment_method=cod`) → order `status=confirmed`, `payment_status=cod_pending` → cash collected on delivery → `POST /admin/cod/orders/{id}/collect` → `payment_status=paid`.

**`GET /admin/cod/pending`** — list COD orders awaiting cash collection:

```json
{
  "count": 2,
  "total_pending_amount": 5518.18,
  "orders": [
    {
      "id": "uuid", "order_number": "ORD-…",
      "customer": { "id": "uuid", "full_name": "…", "email": "…", "phone": "…" },
      "grand_total": 2759.09, "cod_fee": 50.0,
      "status": "confirmed", "payment_status": "cod_pending", "placed_at": "…"
    }
  ]
}
```

**`POST /admin/cod/orders/{order_id}/collect`** — mark cash as collected:

**Response `200`:**

```json
{
  "message": "COD payment collected successfully",
  "order_id": "uuid",
  "order_number": "ORD-…",
  "amount_collected": 2759.09,
  "payment_status": "paid",
  "collected_by": "manager@example.com"
}
```

**Errors:** `404 Order not found` · `400 Order was not placed with Cash on Delivery` · `400 COD payment already collected` · `400 Cannot collect COD for order with payment_status '…'` · `400 Cannot collect COD for a cancelled order`

---

## 22. Enums & Status Values Reference

| Enum | Values |
|---|---|
| **UserRole** | `customer` · `staff` · `manager` · `admin` |
| **OrderStatus** | `pending` · `confirmed` · `processing` · `shipped` · `delivered` · `cancelled` · `refunded` |
| **payment_method (order)** | `cod` · `online` |
| **payment_status (order)** | `pending` · `paid` · `cod_pending` · `refund_initiated` · `refund_completed` · `refund_failed` |
| **Payment.status** | `pending` · `succeeded` · `failed` · `refunded` |
| **Payment.provider** | `dummy` · `razorpay` · `cod` |
| **DiscountType** | `percentage` · `fixed` |
| **auth_provider (user)** | `email` · `google` · `both` |
| **Product sort** | `newest` · `oldest` · `price_asc` · `price_desc` · `name_asc` · `name_desc` |
| **Analytics group_by** | `day` · `week` · `month` |

**Order status lifecycle:**

```
pending ──(payment confirmed)──▶ confirmed ──▶ processing ──▶ shipped ──▶ delivered
   │                                 │              │
   └───────────── cancelled ◀────────┴──────────────┘   (not cancellable once shipped/delivered)
                                          │
                                     refunded  (via cancel of a paid order)
```

---

## 23. Business Rules (Pricing / COD / Refunds)

Server-side configuration the frontend should not hardcode (ask backend for changes):

| Rule | Value | Where it applies |
|---|---|---|
| GST / tax | **18%** on (subtotal − discount) | cart totals, checkout |
| Free shipping | subtotal **≥ ₹1000** | cart totals, checkout |
| Shipping cost | **₹50** flat below threshold | cart totals, checkout |
| COD fee | **₹50** flat, added to grand_total | checkout with `payment_method=cod` |
| COD order range | grand_total **₹0 – ₹10000** | checkout (else 400) |
| Restocking fee (cancel) | **0%** pending · **5%** confirmed · **15%** processing | cancel refund amount |
| Refund SLA message | **5 business days** | refund status `message` |
| Access / refresh token TTL | 15 min / 30 days | auth |
| Reset token TTL | 1 hour | forgot-password email link |
| Password minimum | 8 characters | register / reset / set-password |
| Review rating | integer 1–5 | reviews |
| Quantity bounds | 1–999 | cart item add/update |

---

## 24. Typical Frontend Flows

### 24.1 Authentication flow

```
Register ─▶ POST /auth/register ─▶ redirect to login
Login     ─▶ POST /auth/login ─▶ save TokenPair
Google    ─▶ Google button → id_token ─▶ POST /auth/google ─▶ save TokenPair
Any 401   ─▶ POST /auth/refresh ─▶ save new pair ─▶ retry original call (401 again? → logout)
Logout    ─▶ POST /auth/logout ─▶ clear tokens
```

### 24.2 Guest → user cart

```
Guest: generate X-Cart-Session-ID, POST /cart/items …
Login: tokens stored; subsequent cart calls (Bearer) resolve the user's cart.
```

### 24.3 Checkout — online payment (Razorpay)

```
1. POST /addresses             (if needed)
2. POST /checkout              {shipping_address_id, billing_address_id?, payment_method:"online"} → 201 OrderRead (status: pending)
3. POST /payments/create-intent {order_id} → {payment_intent_id (razorpay order_*), amount, currency}
4. Open Razorpay Checkout modal: key_id, amount (paise!), currency:"INR", order_id: payment_intent_id
5. POST /payments/confirm {payment_intent_id} → PaymentRead (status:"succeeded") → order confirmed
6. GET /orders/{id} to show the confirmed order
```

### 24.4 Checkout — Cash on Delivery

```
1. POST /checkout {…, payment_method:"cod"} → 201 (status:"confirmed", payment_status:"cod_pending", cod_fee added)
2. Done — no payment calls. Show "Pay ₹X on delivery".
```

### 24.5 Cancel & refund

```
POST /orders/{id}/cancel {reason?} → CancelOrderResponse (refund.processed = true for paid online orders)
Poll GET /orders/{id}/refund-status → display response.message
```

---

## 25. Endpoint Quick-Reference Table

| # | Method & Path | Auth | Purpose |
|---|---|---|---|
| 1 | `POST /auth/register` | 🔓 | Create account |
| 2 | `POST /auth/login` | 🔓 | Email login → TokenPair |
| 3 | `POST /auth/refresh` | 🔓 | Rotate tokens |
| 4 | `POST /auth/logout` | 🔓 | Revoke refresh token (204) |
| 5 | `GET /auth/me` | 🔒 | Current user |
| 6 | `PUT /auth/profile` | 🔒 | Update profile |
| 7 | `POST /auth/google` | 🔓 | Google sign-in |
| 8 | `POST /auth/set-password` | 🔒 | Google user adds password |
| 9 | `POST /auth/forgot-password` | 🔓 | Send reset link |
| 10 | `POST /auth/reset-password` | 🔓 | Reset with token |
| 11 | `POST /auth/change-password` | 🔒 | Change password |
| 12 | `GET /products/` | 🔓 | List products (filters/sort/page) |
| 13 | `GET /products/{slug}` | 🔓 | Product detail |
| 14 | `POST /products/` | staff+ | Create product |
| 15 | `PUT /products/{id}` | staff+ | Update product |
| 16 | `DELETE /products/{id}` | staff+ | Delete product (204) |
| 17 | `GET /products/{id}/variants` | 🔓 | List variants |
| 18 | `POST /products/{id}/variants` | staff+ | Create variant |
| 19 | `PUT /products/{id}/variants/{vid}` | staff+ | Update variant |
| 20 | `DELETE /products/{id}/variants/{vid}` | staff+ | Delete variant (204) |
| 21 | `GET /products/{id}/images` | 🔓 | List images |
| 22 | `POST /products/{id}/images` | staff+ | Add image |
| 23 | `PUT /products/{id}/images/{iid}` | staff+ | Update image |
| 24 | `DELETE /products/{id}/images/{iid}` | staff+ | Delete image (204) |
| 25 | `POST /products/{id}/images/reorder` | staff+ | Reorder (query params) |
| 26 | `GET /categories` | 🔓 | List categories |
| 27 | `GET /categories/{id}` | 🔓 | Category detail |
| 28 | `POST /categories` | mgr+ | Create category |
| 29 | `PUT /categories/{id}` | mgr+ | Update category |
| 30 | `DELETE /categories/{id}` | mgr+ | Delete category (204) |
| 31 | `GET /cart` | opt | Get cart (guest session or user) |
| 32 | `POST /cart/items` | opt | Add item (201) |
| 33 | `PUT /cart/items/{item_id}` | opt | Update quantity |
| 34 | `DELETE /cart/items/{item_id}` | opt | Remove item |
| 35 | `DELETE /cart` | opt | Clear cart |
| 36 | `POST /cart/coupon` | opt | Apply coupon |
| 37 | `DELETE /cart/coupon` | opt | Remove coupon |
| 38 | `POST /checkout` | 🔒 | Cart → order (201) |
| 39 | `GET /checkout/config` | 🔓 | Checkout pricing config (COD fee/limits, shipping, tax rate) |
| 40 | `GET /addresses` | 🔒 | List my addresses |
| 41 | `POST /addresses` | 🔒 | Create address (201) |
| 42 | `PUT /addresses/{id}` | 🔒 | Update address |
| 43 | `DELETE /addresses/{id}` | 🔒 | Delete address (204) |
| 44 | `POST /addresses/default/{id}` | 🔒 | Set default |
| 45 | `GET /orders` | 🔒 | My orders |
| 46 | `GET /orders/{id}` | 🔒 | Order detail |
| 47 | `GET /orders/number/{order_number}` | 🔒 | Order by number |
| 48 | `POST /orders/{id}/cancel` | 🔒 | Cancel (+ refund) |
| 49 | `GET /orders/{id}/refund-status` | 🔒 | Refund status |
| 50 | `POST /payments/create-intent` | 🔒 | Start online payment |
| 51 | `POST /payments/confirm` | 🔒 | Confirm payment |
| 52 | `POST /webhooks/payment` | signature | Razorpay only — not frontend |
| 53 | `POST /reviews/{product_id}` | 🔒 | Create review |
| 54 | `GET /reviews/products/{id}` | 🔓 | Product reviews |
| 55 | `GET /reviews/product/{id}/rating` | 🔓 | Average rating |
| 56 | `GET /reviews/my-reviews` | 🔒 | My reviews |
| 57 | `PUT /reviews/{review_id}` | 🔒 | Update my review |
| 58 | `DELETE /reviews/{review_id}` | 🔒 | Delete my review (204) |
| 59 | `GET /wishlist` | 🔒 | My wishlist |
| 60 | `POST /wishlist/{product_id}` | 🔒 | Add to wishlist (201) |
| 61 | `DELETE /wishlist/{product_id}` | 🔒 | Remove (204) |
| 62 | `GET /wishlist/check/{product_id}` | 🔒 | In wishlist? |
| 63 | `POST /coupons/validate` | 🔓 | Validate code |
| 64 | `GET /coupons` | mgr+ | List coupons |
| 65 | `GET /coupons/{id}` | mgr+ | Coupon detail |
| 66 | `POST /coupons` | mgr+ | Create coupon (201) |
| 67 | `PUT /coupons/{id}` | mgr+ | Update coupon |
| 68 | `DELETE /coupons/{id}` | mgr+ | Delete coupon (204) |
| 69 | `POST /coupons/generate` | mgr+ | Generate code |
| 70 | `POST /email/test` | mgr+ | Send test email |
| 71 | `GET /analytics/dashboard` | mgr+ | Dashboard stats |
| 72 | `GET /analytics/sales` | mgr+ | Sales report |
| 73 | `GET /analytics/top-products` | mgr+ | Top products |
| 74 | `GET /analytics/orders` | mgr+ | Order stats |
| 75 | `GET /analytics/revenue` | mgr+ | Revenue report |
| 76 | `GET /analytics/customers` | mgr+ | Customer summary |
| 77 | `GET /admin/dashboard` | mgr+ | Admin overview |
| 78 | `GET /admin/orders` | mgr+ | All orders (paginated) |
| 79 | `GET /admin/orders/stats` | mgr+ | Order stats |
| 80 | `GET /admin/orders/{id}` | mgr+ | Order detail |
| 81 | `PUT /admin/orders/{id}/status` | mgr+ | Update status |
| 82 | `GET /admin/users` | admin | All users (paginated) |
| 83 | `GET /admin/users/stats` | admin | User stats |
| 84 | `GET /admin/users/{id}` | admin | User detail |
| 85 | `PUT /admin/users/{id}/role` | admin | Change role |
| 86 | `PUT /admin/users/{id}/status` | admin | Activate/deactivate |
| 87 | `DELETE /admin/users/{id}` | admin | Delete user (204) |
| 88 | `GET /admin/products` | mgr+ | All products (paginated) |
| 89 | `GET /admin/products/export` | admin | Export JSON |
| 90 | `GET /admin/products/{id}` | mgr+ | Product detail |
| 91 | `POST /admin/products/bulk-delete` | admin | Bulk delete (query params) |
| 92 | `POST /admin/products/bulk-update-status` | admin | Bulk active toggle (query params) |
| 93 | `GET /admin/cod/pending` | mgr+ | COD awaiting collection |
| 94 | `POST /admin/cod/orders/{id}/collect` | mgr+ | Mark COD collected |
| 95 | `POST /chat` | 🔓 | AI chatbot reply |
| 96 | `GET /chat/history` | 🔓 | Chat history (stateless — `[]`) |
| 97 | `DELETE /chat/history` | 🔓 | Clear history |

**Legend:** 🔓 public · 🔒 Bearer token · opt — optional auth (guest session or Bearer) · staff+ / mgr+ / admin — minimum role required.

---

*End of documentation. For anything not covered here, the interactive Swagger docs at `/docs` always reflect the live API.*
