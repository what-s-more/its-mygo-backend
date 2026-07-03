# 购物车与订单接口

## 当前实现范围

- 已实现购物车增删改查、结算预校验、创建订单、订单列表/详情、取消待支付订单、支付单查询、模拟支付。
- 创建订单会按商家拆分订单，并生成一个支付单。
- 若下单传入 `shipping_address_id`，后端会校验地址归属，并把下单当时的收货地址保存为订单地址快照。
- 模拟支付成功后，支付单状态变为 `paid`，订单状态从 `pending_payment` 变为 `pending_shipment`。
- 管理端发货需要填写 `logistics_company` 和 `tracking_no`，发货后订单状态变为 `shipping`。
- 用户确认收货后订单状态变为 `completed`，并记录 `received_at`。
- 当前创建订单直接扣减 SKU 库存，并通过统一库存服务写入 `order_lock` 库存流水；取消或超时取消会回补库存并写入 `order_cancel_restore` 流水。
- 已提供支付超时取消、自动确认收货的 service 方法、Celery 任务入口和 Celery beat 定时配置。
- Redis 预扣、积分抵扣等属于后续全量开发任务，接入时必须同步更新前端页面、接口文档和测试。

## 购物车字段

| 字段 | 类型 | 说明 |
|---|---|---|
| sku_id | number | SKU ID |
| product_id | number | 商品 ID |
| product_name | string | 商品名 |
| sku_name | string | 规格名 |
| price_cent | number | 单价，单位分 |
| quantity | number | 数量 |
| checked | boolean | 是否选中 |
| invalid_reason | string/null | 失效原因 |

## GET `/cart`

获取当前用户购物车列表。

## POST `/cart`

增加商品到购物车。

```json
{ "sku_id": 1, "quantity": 2 }
```

## PUT `/cart/{sku_id}`

修改购物车数量和选中状态。

```json
{ "quantity": 3, "checked": true }
```

## DELETE `/cart/{sku_id}`

删除购物车项。

## POST `/cart/checkout`

返回结算确认信息、优惠计算结果和当前用户可用地址列表。

请求：

```json
{
  "items": [{ "sku_id": 1, "quantity": 2 }],
  "coupon_id": 10,
  "points_used": 0
}
```

说明：

- `items` 不传时，使用购物车中 `checked=true` 的商品。
- `coupon_id` 表示用户券 ID，不是优惠券模板 ID。
- `points_used` 当前保留，积分抵扣后续接入。

## POST `/orders`

创建订单。

请求：

```json
{
  "client_order_token": "unique-client-token",
  "shipping_address_id": 1,
  "coupon_id": 10,
  "source_post_id": 1,
  "items": [{ "sku_id": 1, "quantity": 2 }]
}
```

请求要点：

- `client_order_token` 必填，用于幂等。
- `shipping_address_id` 可选；若传入，后端会校验该地址必须属于当前用户，并保存地址快照到订单。
- `coupon_id` 可选，表示用户券 ID；下单成功后该用户券会标记为 `used`。
- `source_post_id` 可选，表示来自社区种草帖；帖子必须已发布、类型为 `grass`，且关联本次购买商品。
- `items` 不传时，使用购物车中已选中的商品。

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "payment_id": 1,
    "payment_no": "PAY202606250001",
    "order_ids": [1, 2],
    "pay_amount_cent": 9900,
    "expire_at": "2026-06-25T16:15:00+08:00"
  }
}
```

## GET `/orders`

分页获取当前用户订单列表。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| status | string | 否 | 订单状态 |
| page | number | 否 | 页码 |
| page_size | number | 否 | 每页数量 |

## GET `/orders/{id}`

获取订单详情。

响应核心字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 订单 ID |
| order_no | string | 订单号 |
| payment_id | number | 支付单 ID |
| merchant_id | number | 店铺 ID |
| status | string | 订单状态 |
| total_amount_cent | number | 商品总金额，单位分 |
| pay_amount_cent | number | 实付金额，单位分 |
| source_post_id | number/null | 来源种草帖 ID |
| source_user_id | number/null | 来源种草帖作者用户 ID |
| shipping_address | object/null | 下单时收货地址快照 |
| logistics_company | string/null | 物流公司 |
| tracking_no | string/null | 物流单号 |
| shipped_at | string/null | 发货时间 |
| received_at | string/null | 确认收货时间 |
| items | array | 订单商品明细 |

`shipping_address` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| receiver_name | string | 收货人 |
| receiver_mobile | string | 收货手机号 |
| province | string | 省 |
| city | string | 市 |
| district | string/null | 区 |
| detail_address | string | 详细地址 |

## POST `/orders/{id}/cancel`

取消未支付订单。仅 `pending_payment` 状态可取消。

## GET `/payments/{id}`

获取支付单详情。

支付单状态当前包括：

| 状态 | 说明 |
|---|---|
| unpaid | 未支付 |
| paid | 已支付 |
| closed | 未支付超时关闭 |
| refunded | 已全额退款 |
| partial_refunded | 已部分退款 |

## POST `/payments/{id}/pay`

模拟支付。当前不接第三方支付；如后续接入沙盒支付，需要同步补支付回调、幂等、前端状态展示和接口文档。

## POST `/orders/{id}/confirm`

确认收货。仅 `shipping` 或 `pending_receipt` 状态可确认。

确认后：

- 订单状态变为 `completed`。
- `received_at` 写入当前时间。

## 订单自动任务

当前已提供两个订单任务入口：

| 任务名 | 说明 |
|---|---|
| `order.cancel_expired_unpaid_orders` | 取消超过支付窗口仍未支付的订单，回补 SKU 库存，并把支付单状态设为 `closed` |
| `order.auto_confirm_received_orders` | 对发货超过配置天数且仍为 `shipping` 的订单自动确认收货 |

配置项：

| 配置 | 默认值 | 说明 |
|---|---|---|
| `ORDER_PAYMENT_EXPIRE_MINUTES` | 15 | 未支付订单超时分钟数 |
| `ORDER_AUTO_CONFIRM_DAYS` | 7 | 发货后自动确认收货天数 |
| `CELERY_CANCEL_UNPAID_INTERVAL_SECONDS` | 300 | Celery beat 扫描未支付超时订单的周期 |
| `CELERY_AUTO_CONFIRM_INTERVAL_SECONDS` | 3600 | Celery beat 扫描自动确认收货订单的周期 |

说明：

- 当前任务逻辑在 `order_service` 中实现，Celery task 只作为入口，便于测试和后续复用。
- 自动确认收货会复用确认收货后的种草奖励逻辑。
- Celery beat 已在 `app/tasks/celery_app.py` 配置；本地运行方式见 `docs/dev-setup.md`。

## POST `/orders/{id}/reviews`

发表订单评价。当前评价创建后默认 `published`，会直接公开展示；管理端保留兼容审核/隐藏能力。

## POST `/orders/{id}/refunds`

申请退货退款。

当前售后状态支持：`pending_approval`、`approved`、`rejected`、`received`、`refunded`。

请求：

```json
{
  "reason_type": "no_longer_needed",
  "reason": "不想要了",
  "refund_amount_cent": 1999
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| reason_type | string | 否 | 售后原因分类，默认 `other`。建议值：`no_longer_needed`、`quality_issue`、`wrong_item`、`other` |
| reason | string | 是 | 售后原因说明 |
| refund_amount_cent | number | 否 | 退款金额，单位分；不传时默认退订单实付金额，不能超过订单实付金额 |

管理端执行退款完成后，订单状态变为 `closed`。若退款金额等于支付单实付金额，支付单状态变为 `refunded`；若小于支付单实付金额，支付单状态变为 `partial_refunded`。

库存回补规则：

- 当前实训版售后按整单处理，尚未拆到订单明细级退货数量。
- 只有售后单已执行“确认收到退货”且退款金额等于订单实付金额时，退款完成会回补订单内全部 SKU 库存，并写入 `refund_restore` 库存流水。
- 未确认收到退货就直接退款，或部分退款，不自动回补库存。

## 管理端发货 `POST /api/v1/admin/orders/{order_id}/ship`

请求：

```json
{
  "logistics_company": "SF Express",
  "tracking_no": "SF123456789"
}
```

说明：

- 仅 `pending_shipment` 状态可发货。
- 商家管理员只能发自己店铺订单。
- 发货后订单状态变为 `shipping`，并记录 `shipped_at`。
- 按实现设计书 6.2，本项目不实现真实物流轨迹查询；`logistics_company` 和 `tracking_no` 只作为发货记录展示，用户端只做确认收货。

## 管理端售后与评价管理接口

- `POST /api/v1/admin/reviews/{review_id}/audit`：兼容旧审核接口；当前评价发布后默认公开，通过为 `published`，拒绝为 `hidden`，用于管理端隐藏不合适内容。
- `GET /api/v1/admin/refunds`：售后列表。
- `POST /api/v1/admin/refunds/{refund_id}/approve`：同意售后。
- `POST /api/v1/admin/refunds/{refund_id}/reject`：拒绝售后。
- `POST /api/v1/admin/refunds/{refund_id}/receive`：确认收到退货。
- `POST /api/v1/admin/refunds/{refund_id}/refund`：确认退款完成。

## 订单状态

| 状态 | 说明 |
|---|---|
| pending_payment | 待支付 |
| pending_shipment | 待发货 |
| shipping | 已发货 |
| pending_receipt | 待收货 |
| completed | 已完成 |
| cancelled | 已取消 |
| after_sale | 售后中 |
| closed | 已关闭 |

## 错误码

| code | 场景 |
|---|---|
| 40006 | `client_order_token` 重复 |
| 40007 | 库存不足 |
| 40008 | 当前订单状态不允许操作 |
