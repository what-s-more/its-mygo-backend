# Alipay Scan-Code Payment API

This project only integrates Alipay sandbox scan-code payment. We do not integrate WeChat Pay.

Full development and manual testing should use the Alipay sandbox endpoints below. The legacy `POST /payments/{id}/pay` mock endpoint is only a backend test/history fallback and should not be exposed in normal frontend business flows.

## Configuration

Set these values in local `.env`. Do not commit real keys.

| Name | Description |
|---|---|
| `ALIPAY_ENABLED` | `true` to enable Alipay sandbox payment |
| `ALIPAY_GATEWAY_URL` | Current sandbox gateway: `https://openapi-sandbox.dl.alipaydev.com/gateway.do`; production gateway: `https://openapi.alipay.com/gateway.do` |
| `ALIPAY_APP_ID` | Alipay app ID |
| `ALIPAY_APP_PRIVATE_KEY` | App private key. For Python SDK use the non-Java PKCS#1 value from sandbox |
| `ALIPAY_PUBLIC_KEY` | Alipay public key for verification |
| `ALIPAY_NOTIFY_URL` | Backend notify URL, e.g. `http://localhost:8000/api/v1/payments/notify/alipay` |
| `ALIPAY_SUBJECT_PREFIX` | Payment subject prefix |

Security rules:
- The private key must stay on the backend.
- Never put Alipay keys in frontend code.
- Never commit sandbox or production keys to GitHub.
- Never print private keys in logs.
- Frontend redirect or polling result is not final proof of payment. Backend verified notify or backend query is authoritative.

## `POST /payments/{payment_id}/alipay/precreate`

Create an Alipay scan-code payment order with `alipay.trade.precreate`.

Preconditions:
- The payment belongs to the current user.
- Payment status is `unpaid`.
- Alipay config is complete.
- If Alipay is not configured, return business error `40005`; do not generate fake QR codes.

Query parameter:

| Name | Type | Required | Description |
|---|---|---|---|
| `force` | boolean | No | Frontend can use `true` when the user clicks “生成/刷新支付宝二维码”. The key requirement is to lock the button while the request is pending, so repeated clicks do not send concurrent precreate requests. |

Response:

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "payment": {
      "id": 1,
      "payment_no": "PAY202607020001",
      "status": "unpaid",
      "pay_amount_cent": 9900,
      "channel": "alipay",
      "alipay_trade_no": null,
      "alipay_qr_code": "https://qr.alipay.com/...",
      "alipay_buyer_logon_id": null,
      "order_ids": [1, 2],
      "paid_at": null
    },
    "qr_code": "https://qr.alipay.com/...",
    "payment_no": "PAY202607020001",
    "expire_minutes": 120
  }
}
```

Cross-shop rule: one cross-shop checkout creates one payment and multiple merchant orders. Generate only one QR code for the shared `payment_id`.

Frontend rule: while this request is pending, disable the QR-code button and show a loading state. Do not fire repeated precreate requests for the same payment, because the first rendered QR code may become stale if later requests overwrite it.

## `POST /payments/{payment_id}/alipay/sync`

Query Alipay payment status from the backend.

If Alipay returns `TRADE_SUCCESS` or `TRADE_FINISHED`, backend writes the Alipay trade number and buyer summary, marks payment as `paid`, and moves all child orders under the payment from `pending_payment` to `pending_shipment`.

If Alipay query returns `ACQ.TRADE_NOT_EXIST`, backend keeps the local payment as `unpaid` and returns the current payment instead of failing the request. This usually means the QR code has not been paid with an Alipay sandbox buyer account yet, or Alipay sandbox has not made the trade queryable. Frontend should tell the user to finish sandbox payment and sync again later.

## `POST /payments/notify/alipay`

Alipay async notify endpoint.

Response is plain text:
- `success`: notify verified and handled.
- `fail`: signature verification failed, missing payment number, or local payment not found.

Rules:
- Verify signature before any state change.
- Use `out_trade_no` to find local `Payment.payment_no`.
- Only `TRADE_SUCCESS` and `TRADE_FINISHED` mark payment as paid.
- Payment success logic is shared internally by Alipay sync and Alipay notify. The legacy mock endpoint reuses the same service path only for backend fallback tests.

## Payment Fields

`GET /payments/{payment_id}` returns:

| Field | Type | Description |
|---|---|---|
| `channel` | string | Normal frontend business uses `alipay`; legacy `mock` may exist only for backend fallback tests or old local data |
| `alipay_trade_no` | string/null | Alipay trade number |
| `alipay_qr_code` | string/null | Alipay QR code content |
| `alipay_buyer_logon_id` | string/null | Buyer account summary |
| `order_ids` | number[] | Orders under this payment |
| `paid_at` | string/null | Paid time |
