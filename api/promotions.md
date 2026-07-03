# 促销

## 当前实现范围

- 已实现基础优惠券模板、领券、我的优惠券、结算抵扣、下单后标记已使用。
- 管理端已提供创建和查看优惠券模板接口。
- 当前只支持一张用户券参与结算。
- 已支持优惠券适用范围：全平台、指定店铺、指定分类、指定商品、指定 SKU。
- 已支持管理端编辑/停用优惠券模板、按用户 ID 批量发券、手动触发过期用户券作废，以及 Celery 过期任务入口和 beat 定时配置。
- 当前暂未实现满减、限时特价和拼团。

## 优惠券

- `GET /promotions/coupons` 可领取优惠券列表
- `POST /promotions/coupons/{id}/claim` 领取优惠券
- `GET /promotions/my-coupons` 我的优惠券
- `GET /admin/promotions/coupons` 管理端优惠券模板列表
- `POST /admin/promotions/coupons` 管理端创建优惠券模板
- `PUT /admin/promotions/coupons/{id}` 管理端编辑优惠券模板
- `POST /admin/promotions/coupons/{id}/disable` 管理端停用优惠券模板
- `POST /admin/promotions/coupons/{id}/batch-grant` 管理端按用户 ID 批量发券
- `POST /admin/promotions/coupons/expire` 管理端手动触发过期用户券作废

### 优惠券字段

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 优惠券模板 ID 或用户券 ID |
| name | string | 名称 |
| scope_type | string | 适用范围：`all`/`platform`/`merchant`/`category`/`product`/`sku` |
| scope_ids | array | 范围 ID 列表；`all`/`platform` 可为空 |
| discount_type | string | amount/percent |
| discount_value | number | `amount` 时为减免金额分值；`percent` 时为折扣百分比，如 80 表示 8 折 |
| min_amount_cent | number | 使用门槛 |
| total_quantity | number | 总库存，0 表示不限制 |
| claimed_quantity | number | 已领取数量 |
| per_user_limit | number | 单用户领取上限 |
| status | string | 模板状态 active/disabled；用户券状态 unused/used/expired/void |
| valid_from | string | 可选，开始时间 |
| valid_to | string | 可选，结束时间 |

### POST `/admin/promotions/coupons`

创建优惠券模板。平台运营可创建任意范围优惠券；商家运营只能创建本店 `merchant` 范围优惠券。

```json
{
  "name": "满 100 减 10",
  "scope_type": "merchant",
  "scope_ids": [1],
  "discount_type": "amount",
  "discount_value": 1000,
  "min_amount_cent": 10000,
  "total_quantity": 100,
  "per_user_limit": 1,
  "valid_from": null,
  "valid_to": null
}
```

范围规则：

- `all` 和 `platform` 表示全平台可用，`scope_ids` 可为空数组。
- `merchant` 表示指定店铺可用，`scope_ids` 填店铺 ID。
- `category` 表示指定分类可用，`scope_ids` 填分类 ID。
- `product` 表示指定商品可用，`scope_ids` 填商品 ID。
- `sku` 表示指定 SKU 可用，`scope_ids` 填 SKU ID。
- 平台运营可创建任意范围优惠券。
- 商家运营只能创建 `scope_type=merchant` 且 `scope_ids` 只包含自己绑定店铺 ID 的优惠券。

### POST `/promotions/coupons/{id}/claim`

用户领取优惠券。后端会校验模板状态、有效期、库存和单用户领取上限。

### PUT `/admin/promotions/coupons/{id}`

编辑优惠券模板，字段与创建接口一致，均为可选字段，只更新传入内容。

示例：

```json
{
  "name": "满 100 减 15",
  "discount_value": 1500,
  "valid_to": "2026-12-31T23:59:59+08:00"
}
```

权限规则：

- 平台运营可编辑任意优惠券模板。
- 商家运营只能编辑本店铺优惠券，且不能把适用范围改成平台券或其他店铺券。

### POST `/admin/promotions/coupons/{id}/disable`

停用优惠券模板。停用后用户不能继续领取，未使用用户券在结算时也会被判定不可用。

### POST `/admin/promotions/coupons/{id}/batch-grant`

按用户 ID 列表批量发券，当前仅平台运营可用。接口会去重用户 ID，只给存在且启用的用户发券，并遵守模板库存和单用户领取上限。

请求：

```json
{
  "user_ids": [1, 2, 3]
}
```

响应：

```json
{
  "granted_count": 2,
  "skipped_user_ids": [3]
}
```

### POST `/admin/promotions/coupons/expire`

手动触发过期用户券作废，当前仅平台运营可用。Celery 任务入口为 `promotion.expire_user_coupons`，已在 `app/tasks/celery_app.py` 配置 beat 定时执行。

相关配置：

| 配置 | 默认值 | 说明 |
|---|---|---|
| `CELERY_EXPIRE_COUPON_INTERVAL_SECONDS` | 300 | Celery beat 扫描过期用户券的周期 |

响应：

```json
{
  "expired_count": 3
}
```

### GET `/promotions/my-coupons`

查询当前用户优惠券。

查询参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| status | string | 可选，unused/used/expired/void |

用户券响应中的 `template` 字段包含优惠券模板信息。

### 结算使用优惠券

`POST /cart/checkout` 和 `POST /orders` 均支持传入 `coupon_id`。此处的 `coupon_id` 是用户券 ID，不是优惠券模板 ID。

```json
{
  "coupon_id": 1
}
```

下单成功后，用户券状态会从 `unused` 变为 `used`。

结算规则：

- 优惠券门槛 `min_amount_cent` 按适用范围内商品金额计算，不按整单金额计算。
- `amount` 固定金额券最多抵扣适用范围内商品金额。
- `percent` 折扣券仅按适用范围内商品金额计算折扣。
- 多店铺订单使用店铺券时，优惠只分摊到适用店铺订单，不会减到其他店铺订单。

### 用户券状态

| 状态 | 说明 |
|---|---|
| unused | 未使用 |
| used | 已使用 |
| expired | 已过期 |
| void | 已作废 |

## 满减（待实现）

- `GET /promotions/full-discounts/active` 当前活动

## 限时特价（待实现）

- `GET /promotions/flash` 列表
- `GET /promotions/flash/{id}` 详情

## 拼团（待实现）

- `POST /promotions/group-buy/{activity_id}/start` 发起拼团
- `POST /promotions/group-buy/{group_order_id}/join` 参团

## 价格计算顺序

限时特价/拼团价 -> 满减满折 -> 优惠券 -> 积分抵扣

当前只接入优惠券。后续接入满减、限时价、拼团、积分抵扣时，需要同步补充价格计算顺序、前端配置页和结算展示。

## 错误码

| code | 场景 |
|---|---|
| 40004 | 活动或优惠券不存在 |
| 40005 | 不满足领取或使用条件 |
| 40008 | 活动未开始、已结束或状态不可用 |
