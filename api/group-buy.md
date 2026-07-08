# 拼团接口

## 统一规则

- 拼团有独立专区，用户从拼团专区或商品详情直接发起/加入，不加入购物车。
- 拼团订单不叠加满减或优惠券，也不参与社区种草奖励。
- 拼团订单可以使用积分抵扣，抵扣比例和单笔上限仍走平台会员积分配置。
- 拼团允许一次购买多件同一 SKU；成团人数按“已支付用户数”计算，不按购买件数计算。
- 第一名用户发起拼团并支付后，团状态为 `pending`，订单状态为 `group_pending`，不会进入商家待发货。
- 24 小时内达到活动配置的成团人数（2 人或 3 人）且成员均已支付后，团状态变为 `success`，相关订单变为 `pending_shipment`，商家开始履约。
- 用户不能重复加入同一个团。
- 商家只能为本店商品和本店 SKU 创建、查看、停用拼团活动；平台可查看和停用全部活动。

## 状态

拼团活动状态：

| 状态 | 说明 |
|---|---|
| active | 可展示、可开团/参团 |
| disabled | 已停用 |

拼团团状态：

| 状态 | 说明 |
|---|---|
| pending | 待成团 |
| success | 已成团 |
| expired | 已过期 |

拼团参与状态：

| 状态 | 说明 |
|---|---|
| pending_payment | 参与订单待支付 |
| paid | 已支付，计入成团人数 |

订单状态新增：

| 状态 | 说明 |
|---|---|
| group_pending | 拼团已支付但待成团；商家端履约列表不展示 |

## `GET /group-buy/activities`

用户端获取当前可用拼团活动。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| merchant_id | number | 否 | 店铺页筛选本店拼团 |

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "id": 1,
      "merchant_id": 1,
      "product_id": 10,
      "sku_id": 20,
      "name": "2 人成团体验价",
      "group_size": 2,
      "group_price_cent": 9900,
      "status": "active",
      "valid_from": null,
      "valid_to": null,
      "product": {},
      "active_groups": [
        {
          "id": 3,
          "activity_id": 1,
          "leader_user_id": 5,
          "status": "pending",
          "joined_count": 1,
          "group_size": 2,
          "expire_at": "2026-07-04T10:00:00"
        }
      ]
    }
  ]
}
```

`active_groups` 只返回未过期、待成团的团，前端可直接展示“正在拼的团”。

## `POST /group-buy/groups/start`

用户发起拼团并创建拼团订单。

请求：

```json
{
  "activity_id": 1,
  "quantity": 2,
  "shipping_address_id": 1,
  "points_used": 0,
  "client_order_token": "unique-token"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| activity_id | number | 是 | 拼团活动 ID |
| quantity | number | 否 | 购买件数，默认 1，必须大于 0 |
| shipping_address_id | number/null | 否 | 收货地址 ID |
| points_used | number | 否 | 使用积分数，仍受平台抵扣上限限制 |
| client_order_token | string | 是 | 幂等 token |

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "group": {
      "id": 3,
      "activity_id": 1,
      "leader_user_id": 5,
      "status": "pending",
      "joined_count": 0,
      "group_size": 2,
      "expire_at": "2026-07-04T10:00:00"
    },
    "order": {
      "payment_id": 12,
      "order_ids": [30],
      "pay_amount_cent": 9900
    }
  }
}
```

前端拿到 `payment_id` 后继续调用支付宝沙箱预创建接口展示二维码。

## `POST /group-buy/groups/join`

用户加入已有拼团并创建拼团订单。

请求：

```json
{
  "group_id": 3,
  "quantity": 2,
  "shipping_address_id": 1,
  "points_used": 0,
  "client_order_token": "unique-token"
}
```

响应同发起拼团。

约束：

- 团必须为 `pending`。
- 团不能过期。
- 当前用户不能已经加入过该团。
- 已支付人数达到成团人数后不能继续加入。
- `quantity` 只影响本用户拼团订单购买件数、支付金额和库存扣减，不影响 `joined_count`。

## 管理端接口

### `GET /admin/promotions/group-buy`

管理端查询拼团活动。

- 平台账号：返回全部拼团活动。
- 商家账号：只返回本店拼团活动。

### `POST /admin/promotions/group-buy`

商家创建拼团活动。

请求：

```json
{
  "product_id": 10,
  "sku_id": 20,
  "name": "2 人成团体验价",
  "group_size": 2,
  "group_price_cent": 9900,
  "valid_from": null,
  "valid_to": null
}
```

规则：

- 仅已入驻商家账号可创建。
- `product_id` 和 `sku_id` 必须属于当前店铺。
- `sku_id` 必须属于 `product_id`。
- `group_size` 只能是 2 或 3。
- `group_price_cent` 必须小于 SKU 当前销售价。

### `POST /admin/promotions/group-buy/{activity_id}/disable`

停用拼团活动。

- 商家只能停用本店活动。
- 平台可停用全部活动。

## 错误码

| code | 场景 |
|---|---|
| 40003 | 商家越权创建或停用非本店拼团 |
| 40004 | 拼团活动、团或 SKU 不存在 |
| 40005 | SKU 不属于商品、拼团价不低于原价、重复参团 |
| 40008 | 活动不可用、未开始、已结束、团已过期、团已满员 |
