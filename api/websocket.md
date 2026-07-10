# WebSocket 与客服接口

当前已实现客服会话、消息持久化、HTTP 兜底发送和基础 WebSocket 实时推送。WebSocket 只负责实时消息推送，不承载支付、扣库存、退款等关键交易逻辑。

## 连接地址

| 地址 | 说明 | 状态 |
|---|---|---|
| `/ws/chat/{conversation_id}?token=xxx` | 用户与商家/平台客服会话 | 已实现基础版 |
| `/ws/orders?token=xxx` | 订单状态通知 | 可选扩展 |
| `/ws/flash/{activity_id}?token=xxx` | 活动服务器时间同步 | 可选扩展 |

## 统一消息格式

```json
{
  "type": "chat.send",
  "request_id": "uuid",
  "payload": {}
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| type | string | 是 | 消息类型 |
| request_id | string | 否 | 客户端生成，用于请求响应关联 |
| payload | object | 是 | 消息内容 |

## 客服模型

### customer_service_conversation

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 会话 ID |
| user_id | number | 普通用户 ID |
| target_type | string | `merchant` / `platform` |
| merchant_id | number/null | 店铺 ID，平台客服会话为空 |
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
| content_type | string | `text` / `image` |
| content | string | 文本内容 |
| image_urls | string[] | 图片消息 |
| is_read | boolean | 是否已读 |
| created_at | datetime | 创建时间 |

## HTTP 兜底接口

用户端：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/customer-service/conversations` | 创建或复用会话 |
| GET | `/api/v1/customer-service/conversations` | 我的会话列表 |
| GET | `/api/v1/customer-service/conversations/{id}/messages` | 消息历史 |
| POST | `/api/v1/customer-service/conversations/{id}/messages` | HTTP 兜底发送消息 |

前端展示约定：

- 创建或复用会话时不要求用户填写首条消息，进入会话后再通过统一消息输入框发送内容。
- 用户首次创建会话时，后端自动写入一条客服欢迎语。商家客服格式为“您好，我是‘XXX（店名）’的客服！请问有什么能帮到您的？”，平台客服格式为“您好，我是‘一次买够’平台的客服！请问有什么能帮到您的？”。自动回复只在新会话创建时发送一次，复用已有会话不重复发送；当前不提供平台或商家编辑自动回复。
- 商品详情页使用右下角商家客服弹窗，自动关联当前商品和店铺。
- 订单详情页提供“联系商家客服”和“联系平台客服”两个按钮，均使用右下角弹窗，并自动关联当前订单；订单列表不直接显示联系客服入口。
- 用户中心内嵌客服消息板块，`/customer-service` 保留为兼容页，继续承担会话列表、平台客服入口、历史会话管理和基础 WebSocket 推送。
- 平台端和商家端客服会话展示为双栏工作台。后端状态仍为 `open/closed`，前端业务文案分别展示为“进行中/已结束”，关闭会话操作展示为“结束”。

管理端：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/admin/customer-service/conversations` | 商家查看本店商家客服会话；平台只查看平台客服会话 |
| GET | `/api/v1/admin/customer-service/conversations/{id}/messages` | 查看消息历史 |
| POST | `/api/v1/admin/customer-service/conversations/{id}/messages` | 商家或平台回复各自范围内的消息 |
| POST | `/api/v1/admin/customer-service/conversations/{id}/close` | 关闭会话 |

## 客服消息类型

| type | 方向 | payload | 说明 |
|---|---|---|---|
| `chat.send` | 客户端 -> 服务端 | `{ "content_type": "text", "content": "hello", "image_urls": [] }` | 发送消息 |
| `chat.message` | 服务端 -> 客户端 | `CustomerServiceMessage` | 推送新消息 |
| `chat.ack` | 服务端 -> 客户端 | `{ "request_id": "uuid" }` | 确认收到 |
| `conversation.closed` | 服务端 -> 客户端 | `{ "conversation_id": 1 }` | 会话关闭 |
| `ping` | 双向 | `{}` | 心跳 |
| `pong` | 双向 | `{}` | 心跳响应 |
| `error` | 服务端 -> 客户端 | `{ "code": 40002, "message": "未登录" }` | 错误 |

## 权限规则

- 用户只能创建和进入自己的客服会话。
- 商家只能查看和回复 `target_type=merchant` 且 `merchant_id` 为本店的会话。
- 平台只查看和回复 `target_type=platform` 的平台客服会话，不查看、不处理商家会话。
- 会话关联订单时，后端必须校验该订单属于当前用户和目标商家。
- 会话关联商品时，后端必须校验商品属于目标商家。

## 实现要求

- 消息必须先落库，再通过 WebSocket 推送。
- WebSocket 断开后，前端重新连接并通过 HTTP 消息历史补齐漏收消息。
- 图片消息复用上传接口返回的 URL。
- 关键错误使用统一错误码：`40002` 未登录，`40003` 无权限，`40004` 会话不存在，`40008` 会话已关闭。
- 客服 WebSocket 不参与订单支付、库存扣减、退款等关键交易事务。

## AI 购物助手接口

当前 AI 助手为最小可用版：用户端商城页面右侧悬浮入口调用后端统一接口。后端优先使用 qwen-flash 的 OpenAI 兼容接口；未配置 API Key 或模型请求失败时，自动降级为项目内预设提示词和规则化回复。当前不读取实时商品/订单数据。

### `POST /api/v1/ai-assistant/chat`

认证：可匿名访问；若前端已登录，会自动带用户 token，但当前接口不读取私有数据。

请求：

```json
{
  "message": "优惠券和积分怎么一起用？",
  "history": [
    { "role": "assistant", "content": "你好，我是一次买够 AI 购物助手。" },
    { "role": "user", "content": "拼团能用优惠券吗？" }
  ]
}
```

响应：

```json
{
  "reply": "普通订单的优惠顺序是：商品金额先参与满减，再使用一张优惠券，最后按平台积分抵扣上限使用积分。拼团订单不叠加满减和优惠券，只支持积分抵扣。",
  "provider": "qwen"
}
```

约定：

- `message` 最大 1000 字，`history` 最多 20 条。
- 模型配置项：`AI_ASSISTANT_MODEL=qwen-flash`、`AI_ASSISTANT_BASE_URL`、`DASHSCOPE_API_KEY` 或 `AI_ASSISTANT_API_KEY`、`AI_ASSISTANT_ENABLE_THINKING`。
- `AI_ASSISTANT_API_KEY` 优先级高于 `DASHSCOPE_API_KEY`；两者均为空时返回 `provider=preset` 的兜底回复。
- AI 助手只解释商城功能、购物流程、优惠规则、售后客服入口和社区种草规则。
- AI 助手当前承担咨询和解释能力，订单、支付、退款、库存、积分、优惠券、商品上下架等关键业务状态仍由原业务接口处理。
- 模型 API Key 放在本地 `.env`，不进入仓库。
