# 接口规范

## 统一约定

- 基础前缀：`/api/v1`
- 管理端前缀：`/api/v1/admin`
- WebSocket 前缀：`/ws`
- 请求体默认使用 JSON；上传接口使用 `multipart/form-data`
- 认证方式：`Authorization: Bearer <access_token>`
- 成功响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

- 失败响应：

```json
{
  "code": 40001,
  "message": "参数错误",
  "data": null
}
```

- 分页参数：`page` 默认 `1`，`page_size` 默认 `20`，最大 `100`
- 分页响应：

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

## 字段约定

| 类型 | 约定 |
|---|---|
| 主键 | `id`，整数或字符串由后端模型决定 |
| 时间 | ISO 8601 字符串，例如 `2026-06-25T16:00:00+08:00` |
| 金额 | 统一使用分，字段名以 `_cent` 结尾 |
| 状态 | 使用各业务接口文档和后端 schema 中约定的英文枚举 |
| 图片 | 返回可访问 URL，上传接口负责生成 |

## 排序约定

- `sort=latest` 最新
- `sort=hot` 热度
- `sort=sales_desc` 销量降序
- `sort=price_asc` 价格升序
- `sort=price_desc` 价格降序

## 通用错误码

| code | 含义 |
|---|---|
| 0 | 成功 |
| 40001 | 参数错误 |
| 40002 | 未登录 |
| 40003 | 无权限 |
| 40004 | 资源不存在 |
| 40005 | 业务校验失败 |
| 40006 | 重复提交 |
| 40007 | 库存不足 |
| 40008 | 状态不允许 |
| 40009 | 文件不合法 |
| 50000 | 系统异常 |
