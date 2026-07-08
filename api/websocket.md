# WebSocket 与客服接口规划

当前项目尚未完整实现客服 WebSocket。本文作为移交后开发客服、订单通知和活动对时的接口约定。WebSocket 只负责实时推送，不承载支付、扣库存、退款等关键交易逻辑。

## 连接地址规划

| 地址 | 说明 | 状态 |
|---|---|---|
| `/ws/chat/{conversation_id}?token=xxx` | 用户与商家客服会话 | 移交后实现 |
| `/ws/orders?token=xxx` | 订单状态通知 | 后续实现 |
| `/ws/flash/{activity_id}?token=xxx` | 限时价活动服务器时间同步 | 后续实现 |

## 统一消息格式

```json
{
  "type": "chat.send",
  "request_id": "uuid",
  "payload": {}
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| type | string | 是 | 消息类型 |
| request_id | string | 否 | 客户端生成，用于请求响应关联 |
| payload | object | 是 | 消息内容 |

## 客服模型建议

### customer_service_conversation

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 会话 ID |
| user_id | number | 普通用户 ID |
| merchant_id | number | 店铺 ID |
| product_id | number/null | 关联商品 |
| order_id | number/null | 关联订单 |
| status | string | `open` / `closed` |
| last_message_at | datetime/null | 最近消息时间 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

### customer_service_message

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 消息 ID |
| conversation_id | number | 会话 ID |
| sender_type | string | `user` / `merchant` / `platform` |
| sender_id | number | 发送者 ID |
| content_type | string | `text` / `image` / `system` |
| content | string | 文本内容或系统提示 |
| image_urls | string[] | 图片消息 |
| is_read | boolean | 是否已读 |
| created_at | datetime | 创建时间 |

## HTTP 兜底接口建议

用户端：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/customer-service/conversations` | 创建或复用会话 |
| GET | `/api/v1/customer-service/conversations` | 我的会话列表 |
| GET | `/api/v1/customer-service/conversations/{id}/messages` | 消息历史 |
| POST | `/api/v1/customer-service/conversations/{id}/messages` | HTTP 兜底发送消息 |

管理端：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/admin/customer-service/conversations` | 商家查看本店会话，平台监管查看全平台 |
| GET | `/api/v1/admin/customer-service/conversations/{id}/messages` | 查看消息历史 |
| POST | `/api/v1/admin/customer-service/conversations/{id}/messages` | 商家回复消息 |
| POST | `/api/v1/admin/customer-service/conversations/{id}/close` | 关闭会话 |

## 客服消息类型

| type | 方向 | payload | 说明 |
|---|---|---|---|
| `chat.send` | 客户端 -> 服务端 | `{ "content_type": "text", "content": "hello", "image_urls": [] }` | 发送消息 |
| `chat.message` | 服务端 -> 客户端 | `CustomerServiceMessage` | 推送新消息 |
| `chat.read` | 客户端 -> 服务端 | `{ "message_ids": [1, 2] }` | 已读回执 |
| `conversation.closed` | 服务端 -> 客户端 | `{ "conversation_id": 1 }` | 会话关闭 |
| `ping` | 双向 | `{}` | 心跳 |
| `pong` | 双向 | `{}` | 心跳响应 |
| `error` | 服务端 -> 客户端 | `{ "code": 40002, "message": "未登录" }` | 错误 |

## 权限规则

- 用户只能创建和进入自己的客服会话。
- 商家只能查看和回复自己店铺的会话。
- 平台可监管查看全平台会话；是否允许平台介入回复需要后续单独设计，默认只读监管。
- 会话关联订单时，后端必须校验该订单属于当前用户和目标商家。
- 会话关联商品时，后端必须校验商品属于目标商家。

## 实现要求

- 消息必须先落库，再通过 WebSocket 推送。
- WebSocket 断开后，前端重新连接并通过 HTTP 消息历史补齐漏收消息。
- 图片消息复用上传接口返回的 URL。
- 关键错误使用统一错误码：`40002` 未登录，`40003` 无权限，`40004` 会话不存在，`40008` 会话已关闭。
- 客服 WebSocket 不参与订单支付、库存扣减、退款等关键交易事务。
