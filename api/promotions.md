# 促销接口

## 当前范围

当前已实现优惠券、满减、拼团、积分抵扣和会员积分配置。限时价、营销标签仍属于后续全量开发任务。

正常用户下单的价格链为：

1. 商品销售价，后续可接入限时价；拼团订单使用独立拼团价。
2. 满减活动：一个订单只能选择一种满减。
3. 用户优惠券：一个订单只能选择一张用户券。
4. 积分抵扣：积分类似账户余额，可与任何优惠叠加，但受平台配置的单笔抵扣上限限制。
5. 支付宝沙箱支付剩余金额。

拼团订单是独立购买链路：不进入购物车，不叠加满减或优惠券，不参与社区种草奖励；仅允许使用积分抵扣后进入支付宝沙箱支付。拼团接口详见 `docs/api/group-buy.md`。

前端不能自行拼优惠金额，只能展示后端 `checkout` 返回的可选项和金额明细。

## 适用范围

内部 `scope_type` 统一使用：

| 值 | 含义 | scope_ids |
|---|---|---|
| all | 全平台 | 空数组 |
| platform | 平台通用，兼容旧数据 | 空数组 |
| category | 指定分类 | 分类 ID |
| merchant | 指定店铺 | 店铺 ID |
| product | 指定商品 | 商品 ID |
| sku | 指定 SKU | SKU ID |

权限规则：

- 平台运营可创建和管理：全平台、分类、商家、商品、SKU 范围的优惠券和满减。
- 商家运营可创建和管理：本店铺、本店商品、本店 SKU 范围的优惠券和满减。
- 商家后台的 `GET /admin/promotions/coupons` 和 `GET /admin/promotions/full-discounts` 只返回该商家自己创建的优惠券/满减，即 `owner_merchant_id` 等于当前商家店铺 ID。
- 商家不能创建、编辑或停用平台创建的促销，即使该促销范围是当前店铺、当前商品或当前 SKU。
- 平台创建并投放到某店铺的促销会在用户端可领取/可使用列表出现，但不会出现在商家后台的“本店优惠券/本店满减”活动管理列表中。
- 商家不能创建或停用其它店铺、商品、SKU 的促销。
- 用户端店铺页传 `merchant_id` 时，只展示平台通用和当前店铺相关促销，不展示其它店铺专属促销。

## 优惠券

### `GET /promotions/coupons`

获取当前可领取优惠券模板。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| merchant_id | number | 否 | 店铺页使用；只返回平台通用和该店铺相关券 |

### `POST /promotions/coupons/{id}/claim`

用户领取优惠券。后端校验模板状态、有效期、库存和单用户限领。

### `GET /promotions/my-coupons`

查询当前用户优惠券。

查询参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| status | string | 可选，`unused/used/expired/void` |

### `POST /admin/promotions/coupons`

创建优惠券模板。

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

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| name | string | 名称 |
| scope_type | string | 适用范围 |
| scope_ids | number[] | 范围 ID |
| owner_merchant_id | number/null | 创建归属。平台创建为 null，商家创建为商家店铺 ID |
| created_by_admin_id | number/null | 创建该模板的后台账号 ID |
| discount_type | string | `amount` 固定金额；`percent` 折扣百分比 |
| discount_value | number | 固定金额单位分；百分比时 80 表示 8 折 |
| min_amount_cent | number | 使用门槛，按适用范围内商品金额计算 |
| total_quantity | number | 总库存，0 表示不限 |
| per_user_limit | number | 单用户限领 |
| valid_from | string/null | 开始时间 |
| valid_to | string/null | 结束时间 |

### `PUT /admin/promotions/coupons/{id}`

编辑优惠券模板，字段同创建接口，均可选。

商家调用时必须同时满足：

- 当前账号是 `merchant_operator`。
- 该模板 `owner_merchant_id` 等于当前账号绑定的 `merchant_id`。
- 新旧 `scope_type/scope_ids` 都属于本店铺、本店商品或本店 SKU。

否则返回 `40003`。

### `POST /admin/promotions/coupons/{id}/disable`

停用优惠券模板。停用后用户不能继续领取，未使用用户券在结算时也不可用。

商家只能停用自己创建的模板；平台创建的模板只能由平台运营停用。

### `POST /admin/promotions/coupons/{id}/batch-grant`

平台按用户 ID 批量发券，商家不可用。

```json
{ "user_ids": [1, 2, 3] }
```

### `POST /admin/promotions/coupons/expire`

平台手动触发过期用户券作废。Celery 任务入口为 `promotion.expire_user_coupons`。

## 满减

### `GET /promotions/full-discounts/active`

获取当前可用满减活动。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| merchant_id | number | 否 | 店铺页使用；只返回平台通用和该店铺相关活动 |

### `POST /admin/promotions/full-discounts`

创建满减活动。

```json
{
  "name": "每满 100 减 10",
  "scope_type": "merchant",
  "scope_ids": [1],
  "min_amount_cent": 10000,
  "discount_amount_cent": 1000,
  "valid_from": null,
  "valid_to": null
}
```

响应中同样包含 `owner_merchant_id` 和 `created_by_admin_id`，含义与优惠券一致。

规则：

- 满减是“每满多减”，例如适用金额 260 元、门槛 100 元、减 10 元，则减 20 元。
- 抵扣金额不会超过适用范围内商品金额。
- 一个订单最终只能选择一种满减。
- 若前端不传 `full_discount_id`，后端为了兼容旧调用会自动选择本单可用的最优满减；正式前端应展示可选项，让用户显式选择。

### `PUT /admin/promotions/full-discounts/{id}`

编辑满减活动，字段同创建接口，均可选。

商家调用时必须同时满足：

- 当前账号是 `merchant_operator`。
- 该活动 `owner_merchant_id` 等于当前账号绑定的 `merchant_id`。
- 新旧 `scope_type/scope_ids` 都属于本店铺、本店商品或本店 SKU。

否则返回 `40003`。

### `POST /admin/promotions/full-discounts/{id}/disable`

停用满减活动。

商家只能停用自己创建的满减活动；平台创建的活动只能由平台运营停用。

## 结算选择

`POST /cart/checkout` 支持：

```json
{
  "full_discount_id": 1,
  "coupon_id": 10,
  "points_used": 100
}
```

响应会返回：

| 字段 | 说明 |
|---|---|
| available_full_discounts | 当前购物车可展示的满减选项，含可用状态和不可用原因 |
| available_coupons | 当前用户券选项，含可用状态和不可用原因 |
| selected_full_discount_id | 本次实际选中的满减 |
| selected_coupon_id | 本次实际选中的用户券 |
| full_discount_amount_cent | 满减抵扣 |
| coupon_discount_amount_cent | 优惠券抵扣 |
| points_discount_amount_cent | 积分抵扣 |
| pay_amount_cent | 支付宝应付金额 |

优惠券门槛按“满减后的适用范围金额”校验。跨店订单选择平台券或平台满减时，后端按适用商品金额分摊到各店铺订单；选择店铺/商品/SKU 范围时，只分摊到适用店铺或商品。

## 错误码

| code | 场景 |
|---|---|
| 40004 | 活动或优惠券不存在 |
| 40003 | 商家越权管理非自建促销或非本店范围促销 |
| 40005 | 不满足领取或使用条件 |
| 40008 | 活动未开始、已结束或状态不可用 |
