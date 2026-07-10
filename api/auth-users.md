# 认证与用户

## 说明

- 本文档只描述普通用户端账号，不包含后台管理员。
- 需要登录的接口必须携带 `Authorization: Bearer <access_token>`。
- 密码由后端先做 SHA-256 摘要，再使用 Bcrypt 加盐哈希保存，避免 Bcrypt 72 字节输入限制。
- 当前已实现注册、登录、刷新、登出、当前用户资料查询和基础资料编辑。
- 登出已支持 token 拉黑；当前实现为内存黑名单，后续接 Redis TTL 持久化。

## POST `/auth/register`

注册普通用户。

### 请求

```json
{
  "mobile": "13800000000",
  "password": "12345678",
  "nickname": "小明"
}
```

### 响应

```json
{ "code": 0, "message": "ok", "data": { "user_id": 1 } }
```

## POST `/auth/login`

登录并返回 `access_token`、`refresh_token`。

### 请求

```json
{ "account": "13800000000", "password": "12345678" }
```

### 响应

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

## POST `/auth/refresh`

刷新令牌。

### 请求

```json
{ "refresh_token": "jwt" }
```

前端约定：用户端 HTTP 拦截器在普通接口返回 401 时，会携带本地 `user_refresh_token` 自动调用本接口；刷新成功后保存新 token 并重放原请求，刷新失败则清除本地用户 token 并切换为未登录状态。

## POST `/auth/logout`

登出并拉黑当前 token。

### 请求头

`Authorization: Bearer <access_token>`

### 响应

```json
{ "code": 0, "message": "ok", "data": null }
```

## GET `/auth/me`

获取当前登录用户资料，等价于 `/users/profile`。

## GET `/users/profile`

获取当前用户资料。

### 响应字段

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 用户 ID |
| mobile | string | 手机号 |
| nickname | string | 昵称 |
| avatar_url | string | 头像 |
| gender | string/null | 性别，建议值：male/female/other |
| birthday | string/null | 生日，格式 YYYY-MM-DD |
| email | string/null | 邮箱 |
| level | string | normal/silver/gold/diamond |
| points | number | 当前积分 |

## PUT `/users/profile`

修改昵称、头像、性别等基础资料。头像可先通过 `POST /upload/image` 上传，拿到 `url` 后写入 `avatar_url`。

### 请求

```json
{
  "nickname": "小明",
  "avatar_url": "/static/uploads/avatar.jpg",
  "gender": "male",
  "birthday": "2000-01-02",
  "email": "user@example.com"
}
```

所有字段均可选；只传需要修改的字段。`birthday` 为空时传 `null`。

## GET `/users/followed-merchants`

获取当前用户关注的店铺列表。用于用户中心或商城首页展示“我关注的店铺”，不应要求用户通过接口返回区查找。

权限：普通用户登录。

### 查询参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| page | number | 否 | 页码，默认 1 |
| page_size | number | 否 | 每页数量，默认 20 |

### 响应

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "list": [
      {
        "merchant": {
          "id": 1,
          "name": "示例店铺",
          "logo_url": "/static/uploads/logo.jpg",
          "announcement": "店铺公告"
        },
        "followed_at": "2026-07-01T10:00:00",
        "follower_count": 8
      }
    ],
    "page": 1,
    "page_size": 20,
    "total": 1
  }
}
```

说明：

- 只返回当前用户已关注且仍启用的店铺。
- `follower_count` 是该店铺当前总关注数，不是当前用户的关注次数。

## GET `/users/favorite-products`

获取当前用户收藏的在售商品列表。用于用户中心或商城首页展示“我收藏的商品”。

权限：普通用户登录。

### 查询参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| page | number | 否 | 页码，默认 1 |
| page_size | number | 否 | 每页数量，默认 20 |

### 响应

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "list": [
      {
        "product": {
          "id": 1,
          "name": "商品名称",
          "cover_url": "/static/uploads/product.jpg",
          "price_cent": 1299,
          "market_price_cent": 1599,
          "merchant_id": 1,
          "merchant_name": "示例店铺",
          "sales_count": 20,
          "tags": []
        },
        "favorited_at": "2026-07-01T10:00:00",
        "favorite_count": 12
      }
    ],
    "page": 1,
    "page_size": 20,
    "total": 1
  }
}
```

说明：

- 只返回当前用户已收藏且仍在售的商品。
- `favorite_count` 是该商品当前总收藏数，不是当前用户的收藏次数。

## 地址接口

当前已实现用户收货地址的增删改查。地址属于普通用户账号，后台管理员不可混用。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/addresses` | 地址列表 |
| POST | `/addresses` | 新增地址 |
| PUT | `/addresses/{id}` | 修改地址 |
| DELETE | `/addresses/{id}` | 删除地址 |

说明：已保存地址允许继续编辑、删除；设置 `is_default=true` 可把某条地址设为默认地址，并自动取消其它默认地址。

### 地址字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| receiver_name | string | 是 | 收货人 |
| receiver_mobile | string | 是 | 收货手机号 |
| province | string | 是 | 省 |
| city | string | 是 | 市 |
| district | string | 否 | 区县 |
| street | string | 否 | 街道/乡镇 |
| detail_address | string | 是 | 详细地址 |
| postal_code | string | 否 | 邮编 |
| address_tag | string | 否 | 地址标签，如家/公司 |
| is_default | boolean | 否 | 是否默认 |

### POST `/addresses`

新增收货地址。当前用户第一条地址会自动成为默认地址；创建或修改地址时设置 `is_default=true` 会取消其它默认地址。

#### 请求

```json
{
  "receiver_name": "张三",
  "receiver_mobile": "13800000000",
  "province": "广东省",
  "city": "深圳市",
  "district": "南山区",
  "street": "粤海街道",
  "detail_address": "科技园测试路 1 号",
  "postal_code": "518000",
  "address_tag": "家",
  "is_default": true
}
```

#### 响应

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "id": 1,
    "user_id": 1,
    "receiver_name": "张三",
    "receiver_mobile": "13800000000",
    "province": "广东省",
    "city": "深圳市",
    "district": "南山区",
    "street": "粤海街道",
    "detail_address": "科技园测试路 1 号",
    "postal_code": "518000",
    "address_tag": "家",
    "is_default": true
  }
}
```

### PUT `/addresses/{id}`

局部修改地址。只传需要修改的字段即可。

### DELETE `/addresses/{id}`

删除地址。删除默认地址后，系统会把当前用户剩余地址中的一条设为默认。

## GET `/users/points/logs`

分页获取积分流水。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| page | number | 否 | 页码，默认 1 |
| page_size | number | 否 | 每页数量，默认 20 |

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "list": [
      {
        "id": 1,
        "user_id": 1,
        "change_points": 10,
        "balance_points": 10,
        "source_type": "grass_conversion",
        "source_id": 100,
        "description": "种草订单确认收货奖励",
        "created_at": "2026-06-27T10:00:00"
      }
    ],
    "page": 1,
    "page_size": 20,
    "total": 1
  }
}
```

当前积分流水由统一积分服务写入，后续签到、会员成长、积分抵扣都应复用该服务，不直接修改 `user.points`。

## GET `/users/points`

获取当前用户积分账户概览。

积分性质类似账户余额，是支付时的金额扣除渠道之一；后续接入结算后，可与优惠券、满减、限时价、拼团等优惠叠加使用。每笔订单可抵扣额度受平台配置限制，例如最多抵扣订单金额的 10%。

响应字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| user_id | number | 用户 ID |
| points | number | 当前积分余额 |
| sign_in_today | boolean | 今日是否已签到 |
| current_streak_days | number | 当前连续签到天数 |
| today_reward_points | number | 今日签到可获得积分，受平台配置影响 |

## POST `/users/sign-in`

每日签到。每个自然日只能签到一次；签到奖励、连续签到递增和封顶值均由平台端配置。

响应字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| signed | boolean | 是否已完成签到 |
| points | number | 签到后的积分余额 |
| reward_points | number | 本次获得积分；重复签到为 0 |
| streak_days | number | 连续签到天数 |
| message | string | 提示信息 |

## GET `/users/level`

获取当前用户会员等级。

会员等级阈值、等级名称和权益由平台端配置。当前成长值按已完成或有效交易订单实付金额累计计算，单位为分。

响应字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| level | string | 等级标识 |
| level_name | string | 等级名称 |
| growth_value_cent | number | 当前成长值，单位分 |
| next_level | string/null | 下一等级标识 |
| next_level_name | string/null | 下一等级名称 |
| next_level_need_cent | number/null | 距下一等级还需成长值，单位分 |
| benefits | string[] | 当前等级权益 |

## 平台配置接口 `/admin/settings/member-points`

平台端可配置会员与积分规则。只有 `platform_operator` 可修改。

```json
{
  "level_rules": [
    {
      "level": "normal",
      "name": "普通会员",
      "threshold_cent": 0,
      "benefits": ["基础积分"],
      "sign_in_bonus_points": 0,
      "max_points_discount_percent": null,
      "points_multiplier": 1.0,
      "benefit_description": "可领取平台优惠券并参与基础积分活动"
    },
    {
      "level": "silver",
      "name": "银卡会员",
      "threshold_cent": 50000,
      "benefits": ["签到加成", "会员活动"],
      "sign_in_bonus_points": 1,
      "max_points_discount_percent": 12,
      "points_multiplier": 1.1,
      "benefit_description": "每日签到额外积分，订单积分抵扣上限提升"
    }
  ],
  "sign_in_base_points": 2,
  "sign_in_streak_increment": 1,
  "sign_in_max_points": 10,
  "points_to_yuan_rate": 100,
  "max_points_discount_percent": 10
}
```

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| level | string | 等级标识，需保持唯一 |
| name | string | 用户可见等级名称 |
| threshold_cent | number | 达到该等级所需成长值，单位分 |
| benefits | string[] | 权益短标签，展示用 |
| sign_in_bonus_points | number | 该等级每日签到额外积分，已生效 |
| max_points_discount_percent | number/null | 该等级单笔积分抵扣上限覆盖值；为 null 时使用全局 `max_points_discount_percent`，已生效 |
| points_multiplier | number | 积分倍率配置，当前用于展示与后续积分发放扩展预留，不改变现有种草奖励固定 1% 规则 |
| benefit_description | string/null | 面向用户展示的权益说明 |

说明：

- `points_to_yuan_rate=100` 表示 100 积分抵扣 1 元。
- 全局 `max_points_discount_percent=10` 表示单笔订单最多使用积分抵扣可抵扣基数的 10%。
- 等级规则按 `threshold_cent` 升序保存；后端会兼容旧配置，缺失的新字段按默认值补齐。
- 普通订单和拼团订单使用积分抵扣时，都会先解析用户当前会员等级，再使用等级专属抵扣上限或全局抵扣上限。

## 错误码

| code | 场景 |
|---|---|
| 40001 | 手机号、密码格式错误 |
| 40002 | token 缺失或失效 |
| 40005 | 手机号已注册、刷新令牌已过期 |
