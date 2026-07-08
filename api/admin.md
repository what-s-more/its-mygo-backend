# 管理端接口

## 统一说明

- 前缀：`/api/v1/admin`
- 认证：除登录、刷新外，均使用 `Authorization: Bearer <access_token>`
- 管理员类型：
  - `platform_operator`：平台运营，可查看全平台数据。
  - `merchant_operator`：商家运营，只能查看和操作自己绑定 `merchant_id` 的数据。
- 普通用户账号和后台管理员账号分离，不能混用登录接口。
- 管理端前端按 `platform` 和 `merchant` 两套 session 分别保存 token。普通管理接口返回 401 时，HTTP 拦截器会使用对应 session 的 refresh token 调用 `/admin/auth/refresh`；刷新成功后重放原请求，刷新失败只清理当前 session 的 token，不影响另一端同时登录状态。

## 通用分页

分页接口统一使用查询参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| page | number | 否 | 1 | 页码，从 1 开始 |
| page_size | number | 否 | 20 | 每页数量 |

分页响应统一放在 `data` 内：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "list": [],
    "page": 1,
    "page_size": 20,
    "total": 0
  }
}
```

## 认证与菜单

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/auth/login` | 管理端登录 |
| POST | `/auth/refresh` | 刷新 token |
| POST | `/auth/logout` | 登出并拉黑当前 token |
| GET | `/auth/me` | 当前管理员信息 |
| GET | `/auth/menus` | 管理端菜单与权限点 |
| POST | `/merchant/register` | 商家自助注册入驻账号 |
| GET | `/merchant/application/me` | 商家查看自己的入驻申请 |
| PUT | `/merchant/application/me` | 商家重新提交入驻资料 |
| GET | `/merchant/applications` | 平台查看商家入驻申请 |
| POST | `/merchant/applications/{id}/audit` | 平台审核商家入驻申请 |
| GET | `/merchant/profile` | 商家查看自己的店铺资料 |
| PUT | `/merchant/profile` | 商家编辑自己的店铺资料 |
| GET | `/accounts` | 管理员账号列表，仅平台运营 |
| PATCH | `/accounts/{id}/status` | 启用或禁用后台账号，仅平台运营 |
| POST | `/accounts/{id}/reset-password` | 重置后台账号密码，仅平台运营 |

### POST `/auth/login`

请求：

```json
{ "username": "admin", "password": "12345678" }
```

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "access_token": "jwt",
    "refresh_token": "jwt",
    "token_type": "Bearer",
    "expires_in": 1800
  }
}
```

### GET `/auth/me`

响应字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 管理员 ID |
| username | string | 登录名 |
| real_name | string | 姓名 |
| role | string | `platform_operator` / `merchant_operator` / `merchant_pending` |
| merchant_id | number/null | 商家管理员绑定店铺 ID |

## 商家入驻

商家账号实际应由商家自助注册。流程为：

1. 商家注册后台账号并提交店铺信息。
2. 商家可登录管理端，但角色为 `merchant_pending`，仅能查看自己的入驻状态。
3. 平台运营审核入驻申请。
4. 审核通过后，系统创建店铺并把该账号升级为 `merchant_operator`，绑定 `merchant_id`。
5. 商家重新登录或刷新当前管理员信息后，获得本店商品、订单等商家权限。

### POST `/merchant/register`

无需登录。

请求：

```json
{
  "username": "merchant_01",
  "password": "12345678",
  "real_name": "商家负责人",
  "merchant_name": "测试店铺",
  "logo_url": "/static/uploads/logo.jpg",
  "announcement": "主营类目、经营范围和入驻理由"
}
```

说明：`announcement` 在入驻流程中表示“入驻申请说明”，供平台审核使用；审核通过创建店铺时不会自动作为用户端店铺公告。店铺公告由商家通过 `PUT /merchant/profile` 单独维护。

响应：`MerchantApplicationResponse`，初始 `status=pending`。

规则：

- `username` 必须唯一。
- 注册后创建后台账号，角色为 `merchant_pending`。
- `merchant_pending` 可以登录管理端，但不能操作商品、订单、促销等商家功能。
- 店铺名称必须唯一；注册或重新提交资料时如果店铺名称已存在，返回 `40005`。

### GET `/merchant/application/me`

商家登录后查看自己的入驻申请状态。

### PUT `/merchant/application/me`

商家登录后重新提交入驻资料。当前实训版不限制重新提交次数。

请求字段均可选：

```json
{
  "merchant_name": "新的店铺名称",
  "logo_url": "/static/uploads/new-logo.jpg",
  "announcement": "补充入驻申请说明"
}
```

规则：

- `pending` 或 `rejected` 状态均可重新提交。
- 重新提交后状态回到 `pending`，清空原拒绝原因。
- 不限制重新提交次数，但店铺名称仍需保持唯一。
- `approved` 状态不允许再修改入驻申请；后续如需改店铺资料，应走店铺资料编辑接口。

### GET `/merchant/profile`

权限：仅 `merchant_operator`。返回当前商家账号绑定店铺的资料。

响应：

```json
{
  "id": 1,
  "name": "测试店铺",
  "logo_url": "/static/uploads/logo.jpg",
  "announcement": "用户端店铺公告"
}
```

### PUT `/merchant/profile`

权限：仅 `merchant_operator`。商家只能编辑自己绑定的店铺资料。

请求字段均可选：

```json
{
  "name": "新的店铺名称",
  "logo_url": "/static/uploads/new-logo.jpg",
  "announcement": "新的用户端店铺公告"
}
```

规则：

- 店铺名称必须唯一。
- `logo_url` 通常来自上传接口返回路径。
- `announcement` 是展示在用户端店铺页的店铺公告，不等同于入驻申请说明。
- `merchant_pending` 未审核商家不能调用该接口。

### GET `/merchant/applications`

权限：仅 `platform_operator`。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| status | string | 否 | `pending` / `approved` / `rejected` |
| page | number | 否 | 页码 |
| page_size | number | 否 | 每页数量 |

### POST `/merchant/applications/{id}/audit`

权限：仅 `platform_operator`。

请求：

```json
{
  "approved": true,
  "reject_reason": null
}
```

审核通过：

- 创建店铺 `merchant`，名称和 Logo 来自入驻申请，店铺公告默认为空，由商家后续维护。
- 申请账号角色从 `merchant_pending` 变为 `merchant_operator`。
- 申请账号绑定新创建的 `merchant_id`。
- 入驻申请状态变为 `approved`。
- 如店铺名称已存在，审核通过会返回 `40005`，需要商家重新提交新的店铺名称。

审核拒绝：

- 入驻申请状态变为 `rejected`。
- 保留拒绝原因。
- 账号仍为 `merchant_pending`，不能获得商品/订单权限。
- 商家可继续调用 `PUT /merchant/application/me` 重新提交，不限制次数。

### GET `/accounts`

权限：仅 `platform_operator`。

说明：商家账号应通过 `/merchant/register` 自助注册和平台审核产生，平台运营不直接创建商家账号。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| keyword | string | 否 | 按用户名或姓名模糊搜索 |
| role | string | 否 | 按 `platform_operator` / `merchant_operator` / `merchant_pending` 过滤 |
| page | number | 否 | 页码 |
| page_size | number | 否 | 每页数量 |

响应列表项：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 管理员 ID |
| username | string | 登录名 |
| real_name | string | 姓名 |
| role | string | 管理员角色 |
| merchant_id | number/null | 绑定店铺 ID |
| is_active | boolean | 是否启用 |
| created_at | string | 创建时间 |

### PATCH `/accounts/{id}/status`

权限：仅 `platform_operator`。

请求：

```json
{ "is_active": false }
```

说明：

- 可禁用或重新启用后台账号。
- 不能禁用当前登录的自己。
- 被禁用账号不能登录管理端。

### POST `/accounts/{id}/reset-password`

权限：仅 `platform_operator`。

请求：

```json
{ "password": "87654321" }
```

说明：密码长度 8-64 位；响应不会返回明文密码。

## 看板

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/dashboard/summary` | 获取运营看板汇总数据 |

### GET `/dashboard/summary`

查询范围：

- 平台运营：全平台。
- 商家运营：订单与商品按当前管理员 `merchant_id` 过滤，用户数仍为平台用户总数。

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "user_count": 10,
    "product_count": 8,
    "order_count": 12,
    "paid_order_count": 6,
    "gross_merchandise_cent": 129900,
    "pending_shipment_count": 2,
    "after_sale_count": 1
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| user_count | number | 用户总数 |
| product_count | number | 商品总数 |
| order_count | number | 订单总数 |
| paid_order_count | number | 已支付有效订单数 |
| gross_merchandise_cent | number | 已支付有效订单实付金额合计，单位分 |
| pending_shipment_count | number | 待发货订单数 |
| after_sale_count | number | 售后中订单数 |

## 用户运营

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/users` | 用户列表 |
| GET | `/operation-logs` | 后台操作日志，仅平台运营 |

### GET `/users`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| keyword | string | 否 | 按手机号或昵称模糊搜索 |
| page | number | 否 | 页码 |
| page_size | number | 否 | 每页数量 |

响应列表项：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 用户 ID |
| mobile | string | 手机号 |
| nickname | string | 昵称 |
| avatar_url | string/null | 头像 |
| level | string | 用户等级 |
| points | number | 积分 |
| is_active | boolean | 是否启用 |
| created_at | string | 注册时间 |

## 后台操作日志

### GET `/operation-logs`

权限：仅 `platform_operator`。商家运营暂不开放全局操作日志，避免查看到其他店铺操作。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| action | string | 否 | 按动作过滤，如 `order.ship` |
| resource_type | string | 否 | 按资源类型过滤，如 `order` |
| page | number | 否 | 页码 |
| page_size | number | 否 | 每页数量 |

响应列表项：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 日志 ID |
| admin_id | number | 操作管理员 ID |
| action | string | 操作动作 |
| resource_type | string | 资源类型 |
| resource_id | number/null | 资源 ID |
| description | string | 操作描述 |
| created_at | string | 操作时间 |

当前已接入的关键动作：

| action | 说明 |
|---|---|
| product.audit | 商品监管兼容接口，当前用于上架/下架 |
| order.ship | 订单发货 |
| refund.approve | 同意售后 |
| refund.reject | 拒绝售后 |
| refund.receive | 确认收到退货 |
| refund.refund | 确认退款完成 |
| coupon.batch_grant | 批量发券 |
| merchant_application.audit | 商家入驻审核 |
| admin_account.status | 启用或禁用后台账号 |
| admin_account.reset_password | 重置后台账号密码 |

## 商品与店铺

| 方法 | 路径 | platform_operator | merchant_operator |
|---|---|---|---|
| GET | `/products` | 全平台商品 | 自动过滤为本店商品 |
| GET | `/products/{id}` | 商品详情 | 仅本店商品可查看 |
| POST | `/products` | 不可用，平台不创建商品 | 仅可创建本店商品 |
| PUT | `/products/{id}` | 编辑商品基础信息 | 仅可编辑本店商品 |
| PATCH | `/products/{id}/skus/{sku_id}` | 编辑 SKU 价格、库存、规格 | 仅可编辑本店商品 SKU |
| GET | `/products/{id}/skus/{sku_id}/stock-logs` | 查看 SKU 库存流水 | 仅可查看本店商品 SKU |
| POST | `/products/{id}/submit-audit` | 兼容旧接口，当前保持/变为上架 | 仅本店商品可调用 |
| POST | `/products/{id}/audit` | 兼容旧接口，通过为上架，拒绝为下架 | 不可用 |
| POST | `/products/{id}/publish` | 商品上架 | 仅本店商品可上架 |
| POST | `/products/{id}/unpublish` | 商品下架 | 仅本店商品可下架 |
| POST | `/products/batch-publish` | 批量上架商品 | 仅本店商品可批量上架 |
| POST | `/products/batch-unpublish` | 批量下架商品 | 仅本店商品可批量下架 |
| POST | `/merchants` | 创建店铺 | 不可用 |
| POST | `/categories` | 创建分类 | 不可用 |

商品接口当前已支持基础创建、列表、详情、编辑、SKU 价格/库存调整、手动库存流水、单个/批量上下架和商家管理员边界。当前只有商家入驻需要事前审核；商品由商家创建后默认上架，平台保留监管和上下架能力。后续进入细化阶段时可补充更完整的规格管理。

### PUT `/products/{id}`

请求字段均为可选字段，仅更新传入内容：

```json
{
  "category_id": 1,
  "name": "每日坚果升级版",
  "description": "新的商品详情",
  "cover_url": "/static/uploads/cover.jpg",
  "image_urls": ["/static/uploads/cover.jpg"]
}
```

响应：`ProductDetailResponse`。

### PATCH `/products/{id}/skus/{sku_id}`

请求字段均为可选字段，仅更新传入内容：

```json
{
  "name": "500g",
  "price_cent": 9900,
  "market_price_cent": 12900,
  "stock": 100,
  "spec_values": { "规格": "500g" }
}
```

响应：更新后的 `ProductDetailResponse`。

## 订单与售后

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/orders` | 管理端订单列表 |
| GET | `/orders/export` | 导出订单 CSV |
| GET | `/orders/{id}` | 管理端订单详情 |
| POST | `/orders/{id}/ship` | 发货 |
| GET | `/refunds` | 售后列表 |
| POST | `/refunds/{id}/approve` | 同意售后 |
| POST | `/refunds/{id}/reject` | 拒绝售后 |
| POST | `/refunds/{id}/receive` | 确认收到退货 |
| POST | `/refunds/{id}/refund` | 执行退款 |

### GET `/orders`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| status | string | 否 | 按订单状态过滤 |
| page | number | 否 | 页码 |
| page_size | number | 否 | 每页数量 |

订单状态：

| 状态 | 说明 |
|---|---|
| pending_payment | 待支付 |
| pending_shipment | 待发货 |
| shipping | 已发货 |
| pending_receipt | 待收货 |
| completed | 已完成 |
| after_sale | 售后中 |
| cancelled | 已取消 |
| closed | 已关闭 |

响应列表项：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 订单 ID |
| order_no | string | 订单号 |
| payment_id | number | 支付单 ID |
| user_id | number | 下单用户 ID |
| merchant_id | number | 店铺 ID |
| status | string | 订单状态 |
| total_amount_cent | number | 商品总金额，单位分 |
| pay_amount_cent | number | 实付金额，单位分 |
| created_at | string | 创建时间 |

### GET `/orders/{id}`

响应在订单列表项基础上增加：

| 字段 | 类型 | 说明 |
|---|---|---|
| items | array | 订单商品明细 |
| shipping_address | object/null | 下单时收货地址快照 |
| logistics_company | string/null | 物流公司 |
| tracking_no | string/null | 物流单号 |
| shipped_at | string/null | 发货时间 |
| received_at | string/null | 确认收货时间 |

`items` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 订单明细 ID |
| product_id | number | 商品 ID |
| sku_id | number | SKU ID |
| product_name | string | 下单时商品名 |
| sku_name | string | 下单时规格名 |
| unit_price_cent | number | 单价，单位分 |
| quantity | number | 数量 |
| total_amount_cent | number | 明细总价，单位分 |

前端约定：平台端和商家端订单表都应提供“详情”入口，详情中直接展示收货地址、物流记录和商品明细，不应要求通过接口返回排查区查看。

### GET `/orders/export`

导出订单 CSV。

权限规则：

- 平台运营导出全平台订单。
- 商家运营只能导出自己绑定店铺的订单。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| status | string | 否 | 按订单状态筛选 |

响应：

- `Content-Type: text/csv; charset=utf-8`
- 文件名格式：`orders-YYYYMMDDHHMMSS.csv`
- 当前导出字段：`id`、`order_no`、`payment_id`、`user_id`、`merchant_id`、`status`、`total_amount_cent`、`pay_amount_cent`、`created_at`

### POST `/orders/{id}/ship`

说明：

- 仅 `pending_shipment` 状态可发货。
- 商家管理员只能发自己店铺订单。
- 发货时必须填写物流公司和物流单号。
- 发货后订单状态变为 `shipping`，并记录 `shipped_at`。
- 按实现设计书 6.2，本项目不接入物流轨迹查询；发货信息只记录 `logistics_company`、`tracking_no` 和 `shipped_at`，用户端通过确认收货完成后续流转。

请求：

```json
{
  "logistics_company": "SF Express",
  "tracking_no": "SF123456789"
}
```

### GET `/refunds`

平台账号返回全平台售后；商家账号只返回本店订单对应的售后，不能查看或处理其他店铺售后。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| status | string | 否 | 售后状态筛选 |
| page | number | 否 | 页码 |
| page_size | number | 否 | 每页数量 |

售后列表项核心字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 售后单 ID |
| order_id | number | 订单 ID |
| order_item_id | number | 订单明细 ID |
| product_id | number | 商品 ID |
| sku_id | number | SKU ID |
| user_id | number | 申请用户 ID |
| quantity | number | 本次退款数量 |
| refund_amount_cent | number | 退款金额，单位分 |
| reason_type | string | 售后原因分类 |
| reason | string | 售后原因说明 |
| image_urls | string[] | 售后凭证图片 URL |
| status | string | 售后状态 |
| origin_order_status | string | 申请售后前的订单状态 |
| logs | array | 售后处理记录，包含 action、message、operator_type、operator_id、created_at |

### POST `/refunds/{id}/refund`

执行退款完成。仅 `approved` 或 `received` 状态可执行。

权限：平台可处理全平台售后；商家只能处理本店订单对应售后。

执行后：

- 售后单状态变为 `refunded`。
- 若订单内全部明细数量都已退款，订单状态变为 `closed`；否则恢复到申请售后前状态。
- 若支付单累计退款金额等于支付单实付金额，支付单状态变为 `refunded`。
- 若支付单累计退款金额小于支付单实付金额，支付单状态变为 `partial_refunded`。
- 若已确认收到退货，退款完成时只回补本售后单对应 SKU 的本次退款数量。

## 促销

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/promotions/coupons` | 优惠券模板列表 |
| POST | `/promotions/coupons` | 创建优惠券模板 |
| PUT | `/promotions/coupons/{id}` | 编辑优惠券模板 |
| POST | `/promotions/coupons/{id}/disable` | 停用优惠券模板 |
| POST | `/promotions/coupons/{id}/batch-grant` | 按用户 ID 批量发券 |
| POST | `/promotions/coupons/expire` | 手动触发过期用户券作废 |

当前促销已实现优惠券模板创建、编辑、停用、领取、范围校验、下单抵扣、按用户 ID 批量发券、手动过期作废、满减活动和拼团基础配置。限时价、营销标签、活动冲突规则、拼团过期失败处理和更完整的跨店金额边界测试属于移交后继续完善内容。

## 社区内容管理

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/community/posts` | 帖子管理列表，默认查询已发布内容 |
| POST | `/community/posts/{id}/audit` | 兼容旧审核接口，通过为公开，拒绝为隐藏 |
| POST | `/community/posts/{id}/hide` | 隐藏帖子 |
| GET | `/community/comments` | 评论管理列表，默认查询已发布内容 |
| POST | `/community/comments/{id}/audit` | 兼容旧审核接口，通过为公开，拒绝为隐藏 |
| POST | `/community/comments/{id}/hide` | 隐藏评论 |

说明：当前规则明确只有商家入驻需要事前审核。帖子和评论发布后默认 `published`，平台管理端保留隐藏、兼容审核接口等管理能力。

## 错误码

| code | HTTP 状态 | 场景 |
|---|---|---|
| 40001 | 422/400 | 参数错误 |
| 40002 | 401 | 管理端 token 缺失、无效或过期 |
| 40003 | 403 | 普通用户访问管理端、角色无权限或越权访问 |
| 40004 | 404 | 数据不存在 |
| 40008 | 400 | 当前状态不允许执行操作，如发货、商家入驻审核、退款 |
