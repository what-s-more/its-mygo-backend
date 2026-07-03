# 商品与店铺接口

## 当前实现范围

- 用户端已实现商品列表、商品详情、分类列表、店铺详情、店铺商品列表。
- 管理端已实现分类创建、商家创建商品、商品列表、商品详情、编辑商品、编辑 SKU、上架、下架。
- 店铺必须通过商家入驻审核创建，平台不能手动创建店铺；商品由审核通过的商家账号创建，平台负责分类维护和商品监管。
- 当前规则明确只有商家入驻需要事前审核；商品创建后默认 `on_sale`。平台保留上架/下架等管理权限。
- 为兼容旧联调脚本，仍保留 `submit-audit` 和 `audit` 接口，但它们不再是必经流程。
- 商家管理员 `merchant_operator` 已按 `merchant_id` 做权限边界，只能查看和操作本店商品。

## 用户端商品列表 `GET /products`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| keyword | string | 否 | 商品名模糊搜索 |
| category_id | number | 否 | 分类 ID |
| merchant_id | number | 否 | 店铺 ID |
| page | number | 否 | 页码，默认 1 |
| page_size | number | 否 | 每页数量，默认 20 |

说明：用户端只返回 `on_sale` 商品。

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "list": [
      {
        "id": 1,
        "name": "每日坚果",
        "cover_url": "/static/uploads/cover.jpg",
        "price_cent": 9900,
        "market_price_cent": 12900,
        "merchant_id": 1,
        "merchant_name": "测试店铺",
        "sales_count": 0,
        "tags": []
      }
    ],
    "page": 1,
    "page_size": 20,
    "total": 1
  }
}
```

## 用户端商品详情 `GET /products/{id}`

说明：用户端只允许查看 `on_sale` 商品。

响应字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 商品 ID |
| name | string | 商品名 |
| description | string | 图文详情 |
| cover_url | string/null | 封面图 |
| images | string[] | 商品图片 |
| status | string | 商品状态 |
| skus | array | SKU 列表 |
| merchant | object | 店铺摘要 |
| review_summary | object | 评价摘要 |

SKU 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | SKU ID |
| name | string | SKU 名称 |
| price_cent | number | 价格，单位分 |
| market_price_cent | number/null | 划线价，单位分 |
| stock | number | 当前库存 |
| spec_values | object | 规格值 |

## 商品评价 `GET /products/{id}/reviews`

分页返回通过审核的评价列表。

## 店铺主页 `GET /merchants/{id}`

返回店铺信息、公告和在售商品入口。

## 分类 `GET /categories`

返回扁平分类列表，字段包含 `id`、`name`、`parent_id`、`sort_order`。后续前端可按 `parent_id` 组装树。

## 管理端通用说明

- 管理端接口前缀：`/api/v1/admin`
- 所有接口需要管理员 token。
- `platform_operator` 可维护分类、审核/管理全平台商品，但不能手动创建店铺或商品。
- `merchant_operator` 只能管理自己绑定店铺的商品，不能创建店铺和分类。

## 管理端店铺 `POST /admin/merchants`

当前接口保留为兼容占位，但不开放给平台手动创建店铺，调用会返回 `40003/403`。店铺创建必须走商家入驻流程：商家注册入驻申请，平台审核通过后系统创建店铺并绑定商家账号。

旧请求示例仅供识别旧调用：

```json
{
  "name": "测试店铺",
  "logo_url": "/static/uploads/logo.jpg",
  "announcement": "店铺公告"
}
```

## 管理端分类 `POST /admin/categories`

权限：仅 `platform_operator`。

请求：

```json
{
  "name": "零食",
  "parent_id": null,
  "sort_order": 0
}
```

## 管理端商品列表 `GET /admin/products`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| keyword | string | 否 | 商品名模糊搜索 |
| category_id | number | 否 | 分类 ID |
| merchant_id | number | 否 | 店铺 ID，商家管理员只能传自己的店铺 ID |
| page | number | 否 | 页码 |
| page_size | number | 否 | 每页数量 |

说明：当前商品创建后默认 `on_sale`；管理端主要展示 `on_sale`、`off_sale` 等运营状态。旧数据或兼容接口可能仍出现 `draft`、`pending_audit`、`audit_rejected`，但它们不再是新商品发布的必经流程。列表项直接返回可运营字段，包括商品 ID、分类 ID、店铺 ID、状态、SKU ID、SKU 价格和库存，前端不应要求使用者通过接口返回排查区查 ID。

响应列表项为 `ProductDetailResponse` 摘要结构，关键字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 商品 ID |
| name | string | 商品名称 |
| description | string | 商品描述 |
| category_id | number/null | 分类 ID |
| status | string | 商品状态 |
| merchant.id | number | 店铺 ID |
| merchant.name | string | 店铺名称 |
| skus[].id | number | SKU ID |
| skus[].name | string | SKU 名称 |
| skus[].price_cent | number | SKU 价格，单位分 |
| skus[].stock | number | SKU 库存 |

## 管理端创建商品 `POST /admin/products`

权限：

- 仅 `merchant_operator` 可创建商品，并且只能使用自己绑定的 `merchant_id`。
- `platform_operator` 调用会返回 `40003/403`，平台只负责分类和商品监管。

请求：

```json
{
  "merchant_id": 1,
  "category_id": 1,
  "name": "每日坚果",
  "description": "商品详情",
  "cover_url": "/static/uploads/cover.jpg",
  "image_urls": ["/static/uploads/cover.jpg"],
  "skus": [
    {
      "name": "默认规格",
      "price_cent": 9900,
      "market_price_cent": 12900,
      "stock": 100,
      "spec_values": { "规格": "500g" }
    }
  ]
}
```

响应：`ProductDetailResponse`，新商品默认 `status=on_sale`。

## 管理端编辑商品 `PUT /admin/products/{product_id}`

权限：平台运营可编辑全平台商品，商家运营只能编辑本店商品。

请求字段均可选，仅更新传入字段：

```json
{
  "category_id": 1,
  "name": "每日坚果升级版",
  "description": "新的商品详情",
  "cover_url": "/static/uploads/new-cover.jpg",
  "image_urls": ["/static/uploads/new-cover.jpg"]
}
```

响应：更新后的 `ProductDetailResponse`。

## 管理端编辑 SKU `PATCH /admin/products/{product_id}/skus/{sku_id}`

权限：平台运营可编辑全平台商品 SKU，商家运营只能编辑本店商品 SKU。

请求字段均可选，仅更新传入字段：

```json
{
  "name": "500g",
  "price_cent": 9900,
  "market_price_cent": 12900,
  "stock": 100,
  "spec_values": { "规格": "500g" }
}
```

说明：当前 SKU 库存变动统一通过库存服务写入流水，记录调整前库存、调整后库存、变动数量和操作来源。已覆盖管理端手动调整、下单扣减、取消/超时取消回补和符合规则的售后库存回补。后续扩展明细级退货数量时，需要同步调整库存回补规则、前端售后页面和测试。

响应：更新后的 `ProductDetailResponse`。

## 管理端 SKU 库存流水 `GET /admin/products/{product_id}/skus/{sku_id}/stock-logs`

权限：平台运营可查看全平台商品 SKU 库存流水，商家运营只能查看本店商品 SKU 库存流水。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| page | number | 否 | 页码，默认 1 |
| page_size | number | 否 | 每页数量，默认 20 |

响应字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 流水 ID |
| product_id | number | 商品 ID |
| sku_id | number | SKU ID |
| before_stock | number | 调整前库存 |
| change_quantity | number | 变动数量，正数增加，负数减少 |
| after_stock | number | 调整后库存 |
| change_type | string | 变动类型 |
| remark | string | 备注 |
| admin_id | number/null | 操作管理员 ID |

当前常用 `change_type`：

| 类型 | 说明 |
|---|---|
| manual_adjust | 管理端手动调整 |
| order_lock | 创建订单扣减库存 |
| order_cancel_restore | 未支付订单取消或超时取消后回补库存 |
| refund_restore | 售后确认收到退货且全额退款后回补库存 |

## 管理端上下架

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/admin/products/{product_id}/submit-audit` | 兼容旧接口，当前会保持/变为 `on_sale` |
| POST | `/admin/products/{product_id}/audit` | 兼容旧接口，通过为 `on_sale`，拒绝为 `off_sale` |
| POST | `/admin/products/{product_id}/publish` | 上架商品，状态变为 `on_sale` |
| POST | `/admin/products/{product_id}/unpublish` | 下架商品，状态变为 `off_sale` |
| POST | `/admin/products/batch-publish` | 批量上架商品，状态变为 `on_sale` |
| POST | `/admin/products/batch-unpublish` | 批量下架商品，状态变为 `off_sale` |

权限：

- 兼容审核接口：仅平台运营可调用 `/audit`；当前用于监管上架/下架，不作为商品发布前置流程。
- 快速上架/下架：平台运营可操作全平台商品，商家运营只能操作本店商品。
- 批量上架/下架：平台运营可操作全平台商品，商家运营只能操作本店商品；只要列表中包含越权商品，接口会拒绝。

审核请求：

```json
{ "approved": true }
```

批量上下架请求：

```json
{ "product_ids": [1, 2, 3] }
```

## 商品状态

| 状态 | 说明 |
|---|---|
| on_sale | 在售 |
| off_sale | 下架 |

## 错误码

| code | HTTP 状态 | 场景 |
|---|---|---|
| 40001 | 400/422 | 参数错误，如未传 SKU |
| 40003 | 403 | 商家管理员越权操作其他店铺数据 |
| 40004 | 404 | 商品、店铺、分类或 SKU 不存在 |
| 40005 | 400 | 商品未上架，不可展示或购买 |
