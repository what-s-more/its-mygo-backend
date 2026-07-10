# 购物车与订单接口

## 当前实现范围

- 已实现购物车增删改查、结算预校验、创建订单、订单列表/详情、取消待支付订单、支付单查询、支付宝沙箱支付。
- 创建订单会按商家拆分订单，并生成一个支付单；支付、待支付取消和超时取消按支付单下的订单组处理。
- 若下单传入 `shipping_address_id`，后端会校验地址归属，并把下单当时的收货地址保存为订单地址快照。
- 支付宝沙箱支付成功后，支付单状态变为 `paid`，订单状态从 `pending_payment` 变为 `pending_shipment`。
- 管理端发货需要填写 `logistics_company` 和 `tracking_no`，发货后订单状态变为 `shipping`。
- 用户确认收货后订单状态变为 `completed`，并记录 `received_at`。
- 当前创建订单直接扣减 SKU 库存，并通过统一库存服务写入 `order_lock` 库存流水；取消或超时取消会回补库存并写入 `order_cancel_restore` 流水。
- 已提供支付超时取消、自动确认收货的 service 方法、Celery 任务入口和 Celery beat 定时配置。
- 满减、优惠券和积分抵扣已接入结算与下单；库存当前通过统一库存服务记录扣减和回补流水。

## 购物车字段

| 字段 | 类型 | 说明 |
|---|---|---|
| sku_id | number | SKU ID |
| product_id | number | 商品 ID |
| merchant_id | number | 店铺 ID |
| merchant_name | string | 店铺名称 |
| merchant_logo_url | string/null | 店铺 Logo，用于购物车店铺分组头像 |
| product_name | string | 商品名 |
| sku_name | string | 规格名 |
| price_cent | number | 单价，单位分 |
| quantity | number | 数量 |
| checked | boolean | 是否选中 |
| source_post_id | number/null | 来自社区种草帖的来源 ID |
| source_label | string/null | 来源展示文案，例如 `种草来源` |
| invalid_reason | string/null | 失效原因，例如 `商品未上架`、`库存不足` |

## GET `/cart`

获取当前用户购物车列表。

前端展示约定：`invalid_reason` 不为空的购物车项必须直接标记为失效，不能参与本地合计、结算预览或提交订单；页面应保留移除入口，并提示用户刷新购物车或调整商品。

## POST `/cart`

增加商品到购物车。

```json
{ "sku_id": 1, "quantity": 2, "source_post_id": 1 }
```

`source_post_id` 可选。用户从社区种草帖进入商品详情并加购时，前端应传入该字段；购物车中要直接展示“种草来源 #ID”。普通帖、商家动态或拼团不传该字段。

## PUT `/cart/{sku_id}`

修改购物车数量和选中状态。

```json
{ "quantity": 3, "checked": true }
```

## DELETE `/cart/{sku_id}`

删除购物车项。

## PATCH `/cart/batch`

批量修改购物车项选中状态，用于全选、取消全选或选择部分商品结算。

请求：

```json
{
  "sku_ids": [1, 2, 3],
  "checked": true
}
```

说明：

- 只会修改当前登录用户自己的购物车项。
- `sku_ids` 最多 100 个。
- 不存在或不属于当前用户的 SKU 会被忽略。

响应同 `GET /cart`。

## DELETE `/cart`

批量删除购物车项。传 `sku_ids` 时只删除指定 SKU；不传或传空对象时清空当前用户购物车。

请求：

```json
{ "sku_ids": [1, 2, 3] }
```

清空购物车：

```json
{}
```

响应同 `GET /cart`。

## POST `/cart/checkout`

返回结算确认信息、优惠计算结果和当前用户可用地址列表。

请求：

```json
{
  "items": [{ "sku_id": 1, "quantity": 2 }],
  "full_discount_id": 1,
  "coupon_id": 10,
  "points_used": 0
}
```

说明：

- `items` 不传时，使用购物车中 `checked=true` 的商品。
- `full_discount_id` 表示本次选择的满减活动 ID；不传时后端兼容旧调用会自动选择当前最优满减，正式前端应展示 `available_full_discounts` 供用户选择。
- `coupon_id` 表示用户券 ID，不是优惠券模板 ID。
- `points_used` 表示本次希望使用的积分数量。积分类似账户余额，是支付金额扣除渠道，可与任何优惠叠加；后端会按平台配置的兑换比例和单笔抵扣上限校验。
- 后端会忽略/拒绝失效商品，前端应先过滤 `invalid_reason` 不为空的购物车项，避免把失效商品作为可结算商品展示。

## POST `/orders`

创建订单。

请求：

```json
{
  "client_order_token": "unique-client-token",
  "shipping_address_id": 1,
  "full_discount_id": 1,
  "coupon_id": 10,
  "points_used": 100,
  "source_post_id": 1,
  "items": [{ "sku_id": 1, "quantity": 2 }]
}
```

请求要点：

- `client_order_token` 必填，用于幂等。
- `shipping_address_id` 可选；若传入，后端会校验该地址必须属于当前用户，并保存地址快照到订单。
- `full_discount_id` 可选，表示本次选择的满减活动 ID。
- `coupon_id` 可选，表示用户券 ID；下单成功后该用户券会标记为 `used`。
- `points_used` 可选，表示本次支付前抵扣积分数量；下单成功会先扣减积分并写积分流水，未支付取消或超时关闭会退回积分。
- `source_post_id` 可选，表示来自社区种草帖；帖子必须已发布、类型为 `grass`，且关联本次购买商品。
- `items` 不传时，使用购物车中已选中的商品。
- 若本次结算包含多个店铺商品，后端会按 `merchant_id` 拆成多张订单，并返回同一个 `payment_id`。

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

跨店订单规则：

- `order_ids` 可能包含多个订单 ID，每张订单只属于一个店铺。
- 多张店铺订单共用一个支付单，支付宝沙箱支付时会把该支付单下所有 `pending_payment` 订单推进到 `pending_shipment`。
- 用户在待支付状态取消其中任意一张子订单时，后端会关闭整笔支付单，并取消该支付单下全部待支付子订单，同时回补所有相关 SKU 库存。
- 支付后，发货、确认收货、售后仍按单张店铺订单处理。

拼团订单不会通过 `/cart` 或 `/orders` 普通下单接口创建，而是通过 `POST /group-buy/groups/start` 或 `POST /group-buy/groups/join` 创建。拼团支付后先进入 `group_pending`，成团后才进入 `pending_shipment`；商家端履约列表不展示待成团订单。

## GET `/orders`

分页获取当前用户订单列表。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| status | string | 否 | 订单状态 |
| page | number | 否 | 页码 |
| page_size | number | 否 | 每页数量 |

前端约定：用户端订单页应提供状态筛选和分页，避免测试数据过多时影响使用；翻页通过 `page`、`page_size` 请求后端。

## GET `/orders/{id}`

获取订单详情。

响应核心字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 订单 ID |
| order_no | string | 订单号 |
| payment_id | number | 支付单 ID |
| merchant_id | number | 店铺 ID |
| merchant_name | string | 店铺名称，用于购物车、订单列表和订单详情展示 |
| merchant_logo_url | string/null | 店铺 Logo，用于订单列表和订单详情展示 |
| status | string | 订单状态 |
| total_amount_cent | number | 商品总金额，单位分 |
| pay_amount_cent | number | 实付金额，单位分 |
| full_discount_amount_cent | number | 满减抵扣金额，单位分 |
| coupon_discount_amount_cent | number | 优惠券抵扣金额，单位分 |
| points_discount_amount_cent | number | 积分抵扣金额，单位分 |
| points_used | number | 使用积分数量 |
| source_post_id | number/null | 来源种草帖 ID |
| source_user_id | number/null | 来源种草帖作者用户 ID |
| shipping_address | object/null | 下单时收货地址快照 |
| logistics_company | string/null | 物流公司 |
| tracking_no | string/null | 物流单号 |
| created_at | string/null | 下单时间 |
| shipped_at | string/null | 发货时间 |
| received_at | string/null | 确认收货时间 |
| items | array | 订单商品明细 |

`items` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 订单明细 ID，用于评价和售后申请 |
| product_id | number | 商品 ID |
| sku_id | number | SKU ID |
| product_name | string | 下单时商品名称快照 |
| sku_name | string | 下单时 SKU 名称快照 |
| cover_url | string/null | 商品封面图；优先取商品封面，缺失时取商品图片列表第一张 |
| unit_price_cent | number | 下单时单价，单位分 |
| quantity | number | 购买数量 |
| total_amount_cent | number | 明细金额，单位分 |

`shipping_address` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| receiver_name | string | 收货人 |
| receiver_mobile | string | 收货手机号 |
| province | string | 省 |
| city | string | 市 |
| district | string/null | 区 |
| street | string/null | 街道/乡镇 |
| detail_address | string | 详细地址 |
| postal_code | string/null | 邮编 |
| address_tag | string/null | 地址标签 |

## POST `/orders/{id}/cancel`

取消未支付订单。仅 `pending_payment` 状态可取消。

若该订单属于跨店支付单，取消任意一张子订单会关闭整笔支付单，并取消该支付单下全部待支付子订单。取消后回补所有被取消订单内 SKU 库存，并将订单状态置为 `cancelled`。

## GET `/payments/{id}`

获取支付单详情。

前端约定：提交订单、支付宝沙箱支付、取消订单、售后退款后，都应能查看支付单状态，不应只依赖接口返回排查区。

支付单状态当前包括：

| 状态 | 说明 |
|---|---|
| unpaid | 未支付 |
| paid | 已支付 |
| closed | 未支付超时关闭 |
| refunded | 已全额退款 |
| partial_refunded | 已部分退款 |

## 支付宝沙箱支付

支付宝沙箱扫码支付。前端通过预创建接口展示二维码，支付后通过同步接口或异步通知推进支付单和订单状态。

前端生成二维码时必须显示 loading，并在请求完成前禁用“生成/刷新支付宝二维码”按钮，避免同一支付单短时间重复预创建导致先显示的二维码过时。

具体接口见 `docs/api/alipay-payment.md`：
- `POST /payments/{id}/alipay/precreate`
- `POST /payments/{id}/alipay/sync`
- `POST /payments/notify/alipay`

## 价格计算与积分抵扣

结算和下单共用后端价格计算链，顺序为：

1. 商品原价或后续活动价。
2. 满减活动。
3. 用户优惠券。
4. 积分抵扣。
5. 支付宝沙箱支付剩余金额。

`POST /cart/checkout` 响应会返回拆分字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| available_full_discounts | array | 当前可展示满减选项，含可用状态、不可用原因、适用金额和预估抵扣 |
| available_coupons | array | 当前用户券选项，含可用状态、不可用原因、适用金额和预估抵扣 |
| selected_full_discount_id | number/null | 本次实际选中的满减活动 |
| selected_coupon_id | number/null | 本次实际选中的用户券 |
| total_amount_cent | number | 商品合计 |
| full_discount_amount_cent | number | 满减抵扣 |
| coupon_discount_amount_cent | number | 优惠券抵扣 |
| points_discount_amount_cent | number | 积分抵扣金额 |
| points_used | number | 实际使用积分 |
| max_points_usable | number | 按当前余额、兑换比例和单笔上限计算出的最多可用积分 |
| discount_amount_cent | number | 总抵扣，兼容旧前端字段 |
| pay_amount_cent | number | 最终待支付金额 |

积分抵扣规则：

- 积分不是优惠活动，而是支付前的金额扣除渠道。
- 积分可与优惠券、满减、后续限时价和拼团叠加。
- 兑换比例 `points_to_yuan_rate` 和单笔抵扣上限 `max_points_discount_percent` 由平台端 `/admin/settings/member-points` 配置。
- 用户传入积分超过 `max_points_usable` 时返回业务错误。
- 创建支付单时扣减积分并写 `order_points_deduction` 流水；未支付取消或超时关闭支付单时写 `order_points_restore` 流水退回积分。

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

请求：

```json
{
  "product_id": 1,
  "score": 5,
  "content": "商品很好，包装完整",
  "image_urls": ["/static/uploads/review-1.jpg"]
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| product_id | number | 是 | 订单内商品 ID |
| score | number | 是 | 评分，1-5；前端使用星级选择 |
| content | string | 否 | 评价文字，最长 1000 字 |
| image_urls | string[] | 否 | 评价图片 URL，由上传接口返回 |

响应 `data` 包含评价 ID、用户 ID、用户昵称/头像摘要、订单 ID、商品 ID、评分、内容、图片和状态。一个订单中有多个商品时，前端必须让用户选择具体商品分别评价；一个用户对同一订单内同一商品只能评价一次。

## POST `/orders/{id}/refunds`

申请退货退款。

当前售后状态支持：`pending_approval`、`approved`、`rejected`、`received`、`refunded`。

当前实训版售后按“订单明细 + 数量”申请：例如同一商品购买 2 件，可以只退 1 件；但每件商品按单件全额退款，不支持 10 元商品只退 5 元。退款金额由后端按该订单明细分摊后的单件实付金额自动计算，前端不能传自定义退款金额。

请求：

```json
{
  "order_item_id": 12,
  "quantity": 1,
  "reason_type": "no_longer_needed",
  "reason": "不想要了",
  "image_urls": ["/static/uploads/refund-1.jpg"]
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| order_item_id | number | 是 | 订单明细 ID，来自订单详情 `items[].id` |
| quantity | number | 否 | 退款数量，默认 1；不能超过该订单明细剩余可退数量 |
| reason_type | string | 否 | 售后原因分类，默认 `other`。建议值：`no_longer_needed`、`quality_issue`、`wrong_item`、`other` |
| reason | string | 是 | 售后原因说明 |
| image_urls | string[] | 否 | 售后凭证图片 URL，由上传接口返回 |

响应 `data` 中 `refund_amount_cent` 为后端计算出的本次退款金额，`quantity` 为本次退款数量，并返回 `order_item_id`、`product_id`、`sku_id`、`image_urls`、`created_at`、`updated_at` 和处理记录 `logs` 方便前端展示。

`RefundResponse` 核心字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 售后单 ID |
| order_id | number | 订单 ID |
| order_item_id | number/null | 订单明细 ID |
| product_id | number/null | 商品 ID |
| sku_id | number/null | SKU ID |
| user_id | number | 申请用户 ID |
| quantity | number | 本次退款数量 |
| refund_amount_cent | number | 后端计算出的退款金额，单位分 |
| reason_type | string | 售后原因分类 |
| reason | string | 售后原因说明 |
| image_urls | string[] | 售后凭证图片 |
| status | string | 售后状态 |
| origin_order_status | string | 申请售后前订单状态 |
| created_at | string/null | 售后申请时间 |
| updated_at | string/null | 最近更新时间 |
| logs | RefundLog[] | 处理记录，按创建时间正序返回 |

管理端执行退款完成后，若订单内全部明细数量都已退款，订单状态变为 `closed`；否则订单回到申请售后前的状态。若支付单累计退款金额等于支付单实付金额，支付单状态变为 `refunded`；否则为 `partial_refunded`。

库存回补规则：

- 售后单已执行“确认收到退货”后再退款完成，会按本次 `order_item_id + quantity` 回补对应 SKU 库存，并写入 `refund_restore` 库存流水。
- 未确认收到退货就直接退款，不自动回补库存。
- 同一订单同一时间只处理一个售后；售后完成或拒绝后，可以继续对剩余可退数量申请售后。

## GET `/orders/refunds`

分页获取当前用户的售后列表。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| status | string | 否 | 售后状态 |
| page | number | 否 | 页码 |
| page_size | number | 否 | 每页数量 |

响应字段同 `RefundResponse`，分页格式与订单列表一致。

前端约定：用户申请售后后，应在“我的售后”列表中展示售后 ID、订单 ID、订单明细 ID、商品 ID、SKU ID、退款数量、状态、退款金额、原因分类、原因说明、凭证数量和处理记录，并支持按状态筛选。

## GET `/orders/refunds/{refund_id}`

获取当前用户某个售后单详情。只能查看自己的售后单，越权访问返回无权限错误。

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
- `logistics_company` 和 `tracking_no` 用于记录并展示商家发货信息，用户端据此查看发货记录并确认收货。
- 商家端前端提供常用快递公司下拉和模拟单号生成按钮，生成内容仍通过本接口保存。

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
| group_pending | 拼团待成团 |
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
