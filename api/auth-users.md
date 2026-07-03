# 认证与用户

## 说明

- 本文档只描述普通用户端账号，不包含后台管理员。
- 需要登录的接口必须携带 `Authorization: Bearer <access_token>`。
- 密码由后端先做 SHA-256 摘要，再使用 Bcrypt 加盐哈希保存，避免 Bcrypt 72 字节输入限制。
- 当前已实现注册、登录、刷新、登出、当前用户资料查询。
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
| level | string | normal/silver/gold/diamond |
| points | number | 当前积分 |

## PUT `/users/profile`

修改昵称、头像、性别等基础资料。

## 地址接口

当前已实现用户收货地址的基础增删改查。地址属于普通用户账号，后台管理员不可混用。后续需要继续补充更细的省市区、街道、邮编、标签等字段展示和校验。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/addresses` | 地址列表 |
| POST | `/addresses` | 新增地址 |
| PUT | `/addresses/{id}` | 修改地址 |
| DELETE | `/addresses/{id}` | 删除地址 |

### 地址字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| receiver_name | string | 是 | 收货人 |
| receiver_mobile | string | 是 | 收货手机号 |
| province | string | 是 | 省 |
| city | string | 是 | 市 |
| district | string | 否 | 区县 |
| detail_address | string | 是 | 详细地址 |
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
  "detail_address": "科技园测试路 1 号",
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
    "detail_address": "科技园测试路 1 号",
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

## 错误码

| code | 场景 |
|---|---|
| 40001 | 手机号、密码格式错误 |
| 40002 | token 缺失或失效 |
| 40005 | 手机号已注册、刷新令牌已过期 |
