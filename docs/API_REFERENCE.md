# Thiramai API Reference

## Authentication

### `POST /auth/login`
- **Body**: `username`, `password` (form data)
- **Returns**: `access_token`, `token_type`, user context

### `GET /auth/me`
- **Auth**: Bearer token required
- **Returns**: current user profile and role/org context

## Personal OS

### `GET /personal/os/today-brief`
- **Auth**: Bearer token required
- **Returns**: daily briefing with greeting, tasks, meetings, health, and `business_snapshot`

### `GET /personal/os/morning-brief`
- **Auth**: Bearer token required
- **Returns**: morning-first personal briefing payload

### `GET /personal/os/weekly-review`
- **Auth**: Bearer token required
- **Returns**: weekly review metrics

## Dashboard / Business Intelligence

### `GET /dashboard/business-summary`
- **Auth**: Bearer token required
- **Query**: `org_id` (optional, must match active org), `threshold` (optional)
- **Returns**: revenue today/week/month, GST aggregates, top products

### `GET /dashboard/summary`
- **Auth**: Admin role required
- **Returns**: full admin dashboard revenue/GST summary

### `GET /dashboard/inventory-alerts`
- **Auth**: Admin role required
- **Query**: `threshold` (optional)
- **Returns**: low-stock item rows

### `GET /dashboard/command-center`
- **Auth**: Bearer token required
- **Returns**: unified command center snapshot

## Inventory

### `GET /inventory`
- **Auth**: Staff+ role required
- **Query**: `limit`, `offset`
- **Returns**: inventory items list and total count

### `GET /inventory/alerts`
- **Auth**: Bearer token required
- **Query**: `threshold` (optional)
- **Returns**: `{ ok, count, items: [...] }` low-stock alerts

### `POST /inventory/item`
- **Auth**: Staff/Owner/Admin required
- **Body**: `{ sku_name, quantity, location, unit_price, ... }`
- **Returns**: created inventory item

### `PUT /inventory/item/{item_id}`
- **Auth**: Staff/Owner/Admin required
- **Body**: partial inventory fields
- **Returns**: updated inventory item

### `POST /inventory/movement`
- **Auth**: Staff/Owner/Admin required
- **Body**: movement payload (`inventory_item_id`, `quantity_delta`, etc.)
- **Returns**: movement audit + resulting quantity

## Billing

### `GET /billing/invoices`
- **Auth**: Bearer token required
- **Query**: `limit`, `status` (`pending|unpaid|partial|paid`), `org_id` (optional, must match session org)
- **Returns**: invoice list with line items and payment status

### `POST /billing/invoice`
- **Auth**: Staff/Owner/Admin required
- **Body**: structured invoice payload with lines
- **Returns**: created invoice id and totals

### `POST /billing/payment`
- **Auth**: Staff/Owner/Admin required
- **Body**: `{ invoice_id, amount_inr, method, ... }`
- **Returns**: payment record status

### `GET /billing/bills`
- **Auth**: Bearer token required
- **Returns**: non-GST cash bills

## Brain / Command

### `POST /brain/execute`
- **Auth**: Bearer token required (permission-gated)
- **Body**: `{ command, user_id, organization_id }`
- **Returns**: execution result + governance metadata, with:
  - `response_mode = "llm"` and `ai_summary` when `GROQ_API_KEY` is configured
  - `response_mode = "rule_based"` fallback when Groq key is absent

## Health / Ops

### `GET /health/live`
- **Auth**: public
- **Returns**: liveness signal (`alive`)

### `GET /health/ready`
- **Auth**: public
- **Returns**: readiness checks including Alembic status

## Notes

- All protected endpoints require `Authorization: Bearer <jwt>`.
- Active organization is resolved from JWT; cross-org access is rejected.
- Some admin-only routes are intentionally hidden/limited in production hardening mode.
