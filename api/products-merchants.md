# 商品与店铺接口

## 当前实现范围

- 用户端已实现商品列表、商品详情、分类列表、店铺详情、店铺商品列表；商品详情基础版采用正文描述 + 多图画廊展示。
- 管理端已实现分类创建、商家创建商品、商品列表、商品详情、编辑商品、编辑 SKU、上架、下架、删除，以及商家维护本店名称、Logo 和公告。
- 店铺必须通过商家入驻审核创建，平台不能手动创建店铺；审核通过时店铺名称和 Logo 来自入驻申请，店铺公告默认为空，由商家后续自行维护；商品由审核通过的商家账号创建，平台负责分类维护和商品监管。
- 当前规则明确只有商家入驻需要事前审核；商品创建后默认 `on_sale`。平台保留上架/下架等管理权限。
- 为兼容旧联调脚本，仍保留 `submit-audit` 和 `audit` 接口，但它们不再是必经流程。
- 商家管理员 `merchant_operator` 已按 `merchant_id` 做权限边界，只能查看和操作本店商品。

## 用户端商品列表 `GET /products`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| keyword | string | 否 | 商品名模糊搜索 |
| category_id | number | 否 | 分类 ID；传父级分类时会同时返回其所有子孙分类下的商品 |
| merchant_id | number | 否 | 店铺 ID |
| min_price_cent | number | 否 | 最低价，单位分；按商品 SKU 价格过滤 |
| max_price_cent | number | 否 | 最高价，单位分；按商品 SKU 价格过滤 |
| sort_by | string | 否 | 排序字段：`newest`/`created_at`/`price`/`sales` |
| sort_order | string | 否 | 排序方向：`asc`/`desc`，默认 `desc` |
| page | number | 否 | 页码，默认 1 |
| page_size | number | 否 | 每页数量，默认 20 |

说明：用户端只返回 `on_sale` 商品。`category_id` 必须是存在且启用的分类，否则返回 `40004`。价格筛选会匹配商品任一 SKU；价格排序按商品最低 SKU 价排序。

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
| images | string[] | 商品图片，按上传顺序返回，可用于详情页图文展示 |
| status | string | 商品状态 |
| skus | array | SKU 列表 |
| merchant | object | 店铺摘要 |
| review_summary | object | 评价摘要，包含 `count` 与 `average_score` |

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

分页返回公开评价列表。当前评价发布后默认为 `published`，管理端可隐藏不合适评价。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| page | number | 否 | 页码，默认 1 |
| page_size | number | 否 | 每页数量，默认 20 |
| score | number | 否 | 按评分筛选，1-5 |
| has_image | boolean | 否 | `true` 时只返回有图评价 |

响应列表项：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 评价 ID |
| user_id | number | 评价用户 ID |
| user_nickname | string/null | 评价用户昵称 |
| user_avatar_url | string/null | 评价用户头像 |
| order_id | number | 来源订单 ID |
| product_id | number | 商品 ID |
| score | number | 评分，1-5 |
| content | string | 评价内容 |
| image_urls | string[] | 评价图片 |
| status | string | 当前只公开返回 `published` |

前端约定：商品详情页应展示 `review_summary` 和评价列表；评分用星级展示，支持按评分筛选和只看有图；评价图片用上传接口得到的 URL 数组保存并展示缩略图；用户信息优先展示 `user_nickname` 和 `user_avatar_url`，为空时再用用户 ID 兜底。

## 店铺主页 `GET /merchants/{id}`

返回店铺基础信息。用户端店铺页应展示店铺 ID、店铺名、Logo、公告，并提供店铺商品列表入口。

路径参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | number | 是 | 店铺 ID |

响应 `data`：

```json
{
  "id": 1,
  "name": "测试店铺",
  "logo_url": "/static/uploads/logo.jpg",
  "announcement": "店铺公告"
}
```

错误码：

| code | HTTP | 说明 |
|---|---|---|
| 40004 | 404 | 店铺不存在 |

## 店铺商品 `GET /merchants/{id}/products`

返回指定店铺的在售商品列表，分页规则与 `GET /products` 一致。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| min_price_cent | number | 否 | 最低价格，单位分 |
| max_price_cent | number | 否 | 最高价格，单位分 |
| sort_by | string | 否 | `newest`、`price`、`sales` |
| sort_order | string | 否 | `asc` 或 `desc`，默认按最新倒序 |
| page | number | 否 | 页码，默认 1 |
| page_size | number | 否 | 每页数量，默认 20 |

响应 `data`：

```json
{
  "list": [
    {
      "id": 1,
      "name": "商品名称",
      "cover_url": "/static/uploads/product.jpg",
      "price_cent": 1299,
      "market_price_cent": 1599,
      "merchant_id": 1,
      "merchant_name": "测试店铺",
      "sales_count": 10,
      "tags": []
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1
}
```

前端约定：

- 用户端商品卡片和商品详情中的店铺 ID/店铺名应能跳转到 `/merchants/{id}`。
- 店铺页正常展示店铺关注状态、关注数、可用优惠券、商品列表、价格区间筛选和排序，不应要求用户通过接口返回区查店铺商品。
- 用户中心或商城首页应通过 `/users/followed-merchants` 展示当前用户关注的店铺列表。
- 店铺商品详情可复用普通商品详情与加入购物车能力。

## 店铺关注 `GET /merchants/{id}/follow`

返回店铺关注状态。未登录也可调用，此时 `followed=false`，仍返回关注数。

响应：

```json
{
  "merchant_id": 1,
  "followed": false,
  "follower_count": 10
}
```

## 关注店铺 `POST /merchants/{id}/follow`

权限：普通用户登录。重复关注不会重复增加关注数，接口保持幂等。

响应同 `GET /merchants/{id}/follow`。

## 取消关注店铺 `DELETE /merchants/{id}/follow`

权限：普通用户登录。未关注时取消不会报错，接口保持幂等。

响应同 `GET /merchants/{id}/follow`。

## 商品收藏状态 `GET /products/{id}/favorite`

返回商品收藏状态。未登录也可调用，此时 `favorited=false`，仍返回收藏数。

响应：

```json
{
  "product_id": 1,
  "favorited": false,
  "favorite_count": 12
}
```

## 收藏商品 `POST /products/{id}/favorite`

权限：普通用户登录。重复收藏不会重复增加收藏数，接口保持幂等。

响应同 `GET /products/{id}/favorite`。

## 取消收藏商品 `DELETE /products/{id}/favorite`

权限：普通用户登录。未收藏时取消不会报错，接口保持幂等。

响应同 `GET /products/{id}/favorite`。

## 分类 `GET /categories`

返回启用中的扁平分类列表，字段包含 `id`、`name`、`parent_id`、`sort_order`。后端按一级分类优先、父级、`sort_order`、`id` 排序；前端应按 `parent_id` 组装树形展示。

分类规则：

- 最多支持三级分类。
- `parent_id = null` 表示一级分类。
- `sort_order` 只表示同一父级下的展示顺序，数字越小越靠前。
- 用户端和管理端商品列表按父级分类筛选时，会包含所有子孙分类下的商品。

前端约定：用户端首页使用紧凑胶囊分类筛选条。默认只展示一级分类；选中父分类后才展开其直接子分类，继续选中子分类后再展开下一层；没有子分类时不显示下级区域。用户端只展示分类名称，不展示分类 ID。管理端可展示 ID、父级关系、完整路径和排序，便于运营维护。

## 首页轮播 `GET /home/banners`

公开接口，不需要登录。返回平台启用中的首页轮播图，按 `sort_order`、`id` 排序。

响应字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 轮播图 ID |
| title | string | 标题 |
| subtitle | string/null | 副标题 |
| image_url | string | 图片地址，来自上传接口 |
| target_type | string | `none`/`product`/`url` |
| target_id | number/null | `product` 时为商品 ID |
| target_url | string/null | `url` 时为跳转链接 |
| sort_order | number | 排序，数字越小越靠前 |
| is_active | boolean | 是否展示；公开接口只返回 true |

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

## 商家端店铺资料 `GET /admin/merchant/profile`

权限：仅 `merchant_operator`。返回当前商家账号绑定店铺的 `id`、`name`、`logo_url`、`announcement`。

## 商家端店铺资料 `PUT /admin/merchant/profile`

权限：仅 `merchant_operator`。商家编辑自己绑定店铺的名称、Logo 和用户端店铺公告。

请求：

```json
{
  "name": "新的店铺名称",
  "logo_url": "/static/uploads/new-logo.jpg",
  "announcement": "新的店铺公告"
}
```

规则：

- 店铺名称必须唯一，不能与其他店铺冲突。
- `logo_url` 来自上传接口返回值。
- `announcement` 展示在用户端店铺主页；入驻申请里的说明只供平台审核，不会自动成为店铺公告。
- 平台运营不能通过该接口替商家编辑资料。

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

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| name | string | 是 | 分类名称，1-50 字 |
| parent_id | number/null | 否 | 父级分类 ID；不传或传 null 表示一级分类 |
| sort_order | number | 否 | 同一父级下排序，数字越小越靠前，默认 0 |

错误码：

| code | HTTP | 说明 |
|---|---|---|
| 40004 | 404 | 父级分类不存在或已停用 |
| 40005 | 400 | 父级分类已是三级分类，不能继续添加子分类 |

## 管理端分类 `PUT /admin/categories/{id}`

权限：仅 `platform_operator`。

请求字段均可选，只更新传入字段：

```json
{
  "name": "休闲零食",
  "parent_id": null,
  "sort_order": 10
}
```

规则：

- 不能把分类移动到自己或自己的子孙分类下。
- 移动后整棵分类子树仍不能超过三级。
- 父级分类必须存在且启用。

## 管理端分类 `DELETE /admin/categories/{id}`

权限：仅 `platform_operator`。

当前是软停用，不做物理删除。停用后分类不会出现在用户端/商家端分类列表，也不能继续用于新建或编辑商品。

停用限制：

- 分类下还有启用子分类时不能停用。
- 分类下还有商品占用时不能停用，需要先迁移商品分类或处理商品。

## 管理端首页轮播 `GET /admin/home-banners`

权限：仅 `platform_operator`。返回全部轮播图，包含已停用数据，供平台运营维护。

## 管理端首页轮播 `POST /admin/home-banners`

权限：仅 `platform_operator`。

请求：

```json
{
  "title": "夏日好物专场",
  "subtitle": "清爽生鲜与居家好物限时推荐",
  "image_url": "/static/uploads/banner.jpg",
  "target_type": "product",
  "target_id": 12,
  "target_url": null,
  "sort_order": 10,
  "is_active": true
}
```

规则：

- `image_url` 必填，来自上传接口返回值。
- `target_type=none` 表示不跳转。
- `target_type=product` 时必须填写存在的商品 ID；用户端点击跳转 `/products/{target_id}`。
- `target_type=url` 时必须填写 `target_url`；用户端点击打开该链接。
- 后端会按 `target_type` 清理无关字段：`none` 会清空 `target_id` 和 `target_url`，`product` 会清空 `target_url`，`url` 会清空 `target_id`。
- 轮播图启停不影响商品状态，只影响首页展示。

## 管理端首页轮播 `PUT /admin/home-banners/{id}`

权限：仅 `platform_operator`。字段均可选，规则同创建接口。

## 管理端首页轮播 `DELETE /admin/home-banners/{id}`

权限：仅 `platform_operator`。物理删除轮播图配置，不删除上传文件。

## 管理端商品列表 `GET /admin/products`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| keyword | string | 否 | 商品名模糊搜索 |
| category_id | number | 否 | 分类 ID；传父级分类时会同时返回其所有子孙分类下的商品 |
| merchant_id | number | 否 | 店铺 ID，商家管理员只能传自己的店铺 ID |
| min_price_cent | number | 否 | 最低价，单位分 |
| max_price_cent | number | 否 | 最高价，单位分 |
| sort_by | string | 否 | `newest`/`created_at`/`price`/`sales` |
| sort_order | string | 否 | `asc`/`desc` |
| page | number | 否 | 页码 |
| page_size | number | 否 | 每页数量 |

说明：当前商品创建后默认 `on_sale`；管理端主要展示 `on_sale`、`off_sale` 等运营状态。删除后的 `deleted` 商品从管理端列表和用户端列表隐藏，历史订单、评价、售后等记录保留商品引用。旧数据或兼容接口可能仍出现 `draft`、`pending_audit`、`audit_rejected`，但它们不再是新商品发布的必经流程。列表项直接返回可运营字段，包括商品 ID、分类 ID、店铺 ID、状态、SKU ID、SKU 价格和库存，前端不应要求使用者通过接口返回排查区查 ID。

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
  "description": "商品详情正文，可包含换行文本。当前不引入富文本编辑器，详情页使用正文 + 多图画廊展示。",
  "cover_url": "/static/uploads/cover.jpg",
  "image_urls": ["/static/uploads/cover.jpg", "/static/uploads/detail-1.jpg"],
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

## 管理端新增 SKU `POST /admin/products/{product_id}/skus`

权限：平台运营可给全平台商品新增 SKU，商家运营只能给本店商品新增 SKU。

请求：

```json
{
  "name": "1kg",
  "price_cent": 18900,
  "market_price_cent": 22900,
  "stock": 50,
  "spec_values": { "规格": "1kg" }
}
```

响应：更新后的 `ProductDetailResponse`。新增 SKU 后，商家端应刷新商品详情和本店商品列表。

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
| DELETE | `/admin/products/{product_id}` | 删除商品，状态变为 `deleted` |
| POST | `/admin/products/batch-publish` | 批量上架商品，状态变为 `on_sale` |
| POST | `/admin/products/batch-unpublish` | 批量下架商品，状态变为 `off_sale` |

权限：

- 兼容审核接口：仅平台运营可调用 `/audit`；当前用于监管上架/下架，不作为商品发布前置流程。
- 快速上架/下架：平台运营可操作全平台商品，商家运营只能操作本店商品。
- 删除商品：平台运营可删除全平台商品，商家运营只能删除本店商品。删除后商品从用户端和管理端列表隐藏。
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
| deleted | 已删除 |

## 错误码

| code | HTTP 状态 | 场景 |
|---|---|---|
| 40001 | 400/422 | 参数错误，如未传 SKU |
| 40003 | 403 | 商家管理员越权操作其他店铺数据 |
| 40004 | 404 | 商品、店铺、分类或 SKU 不存在 |
| 40005 | 400 | 商品未上架，不可展示或购买 |
