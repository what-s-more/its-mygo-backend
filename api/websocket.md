# WebSocket 接口

## 连接地址

- 用户端客服：`/ws/customer-service?token=xxx`
- 订单通知：`/ws/orders?token=xxx`
- 限时活动倒计时：`/ws/flash?token=xxx`

## 统一约定

- 连接时携带 token
- 消息使用 JSON
- 需要定义 `type`、`payload`、`request_id`

## 消息示例

```json
{ "type": "chat.send", "request_id": "uuid", "payload": { "text": "hello" } }
```

## 消息类型

| type | 方向 | 说明 |
|---|---|---|
| `chat.send` | 客户端 -> 服务端 | 发送客服消息 |
| `chat.message` | 服务端 -> 客户端 | 推送客服消息 |
| `order.created` | 服务端 -> 客户端 | 新订单通知 |
| `order.status_changed` | 服务端 -> 客户端 | 订单状态变化 |
| `flash.time_sync` | 服务端 -> 客户端 | 活动服务器时间同步 |
| `ping` | 双向 | 心跳 |
| `pong` | 双向 | 心跳响应 |

## 错误消息

```json
{
  "type": "error",
  "request_id": "uuid",
  "payload": {
    "code": 40002,
    "message": "未登录"
  }
}
```
