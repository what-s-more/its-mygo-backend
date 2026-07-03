# 社区

## 统一说明

- 帖子支持 `normal`、`grass`、`merchant_ad`。
- 当前规则为发布后展示：帖子和评论不做事前审核，创建后默认 `published`。
- 管理端保留内容管理能力，可查询公开/隐藏内容，并对帖子、评论执行隐藏。
- 订单可通过 `source_post_id` 记录种草来源；买家确认收货后，系统给种草帖作者增加积分奖励。
- 当前暂未实现话题标签管理、用户主页、商家广告帖权限细分和完整积分流水展示。

## 帖子接口

- `GET /community/posts`
- `GET /community/posts/{id}`
- `POST /community/posts`
- `DELETE /community/posts/{id}`
- `POST /community/posts/{id}/like`
- `GET /community/posts/{id}/comments`
- `POST /community/posts/{id}/comments`
- 管理端：`GET /admin/community/posts`
- 管理端：`POST /admin/community/posts/{id}/hide`
- 管理端兼容接口：`POST /admin/community/posts/{id}/audit`
- 管理端：`GET /admin/community/comments`
- 管理端：`POST /admin/community/comments/{id}/hide`
- 管理端兼容接口：`POST /admin/community/comments/{id}/audit`

## POST `/community/posts`

发布帖子。帖子创建后状态为 `published`，会直接出现在公开列表。

```json
{
  "type": "grass",
  "title": "零食测评",
  "content": "内容正文",
  "image_urls": ["/static/uploads/a.jpg"],
  "product_ids": [1],
  "topic_tags": ["零食测评"]
}
```

种草帖 `type=grass` 建议关联 `product_ids`。当前实训版不在发帖时强制校验已购；下单使用 `source_post_id` 时仍要求来源帖子为已发布 `grass` 帖，且关联本次购买商品。

## 种草来源下单

创建订单时可传入 `source_post_id`：

```json
{
  "client_order_token": "unique-token",
  "source_post_id": 1
}
```

规则：

- 来源帖子必须是已发布的 `grass` 种草帖。
- 来源帖子必须关联本次购买的商品。
- 买家不能使用自己的种草帖作为来源。
- 买家确认收货后，系统给种草帖作者增加积分奖励，当前规则为 10 积分。
- 奖励通过统一积分服务写入 `points_log`，并按订单去重。

## 帖子字段

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 帖子 ID |
| type | string | normal/grass/merchant_ad |
| status | string | published/hidden |
| author | object | 作者摘要 |
| product_ids | array | 关联商品 ID |
| topic_tags | array | 话题标签 |
| like_count | number | 点赞数 |
| comment_count | number | 评论数 |

## POST `/community/posts/{id}/like`

对已发布帖子点赞或取消点赞。同一用户重复调用会切换状态。

```json
{
  "code": 0,
  "message": "ok",
  "data": { "liked": true, "like_count": 1 }
}
```

## POST `/community/posts/{id}/comments`

发表评论。评论创建后状态为 `published`，会直接在公开评论列表展示。

## 管理端内容管理

### GET `/admin/community/posts`

查询帖子列表。默认查询公开帖子，平台可按状态筛选并隐藏违规内容。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| status | string | 否 | 默认 `published`，可选 `published`、`hidden` |
| page | number | 否 | 页码，默认 1 |
| page_size | number | 否 | 每页数量，默认 20 |

### POST `/admin/community/posts/{id}/hide`

隐藏帖子。隐藏后用户端公开列表不可见。

### POST `/admin/community/posts/{id}/audit`

兼容旧审核接口。当前规则下：

- `approved=true`：帖子保持或变为 `published`。
- `approved=false`：帖子变为 `hidden`。

### GET `/admin/community/comments`

查询评论列表。默认查询公开评论，平台可按状态筛选并隐藏违规内容。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| post_id | number | 否 | 传入时只查询某个帖子评论 |
| status | string | 否 | 默认 `published`，可选 `published`、`hidden` |
| page | number | 否 | 页码，默认 1 |
| page_size | number | 否 | 每页数量，默认 20 |

### POST `/admin/community/comments/{id}/hide`

隐藏评论。

### POST `/admin/community/comments/{id}/audit`

兼容旧审核接口。当前规则下：

- `approved=true`：评论保持或变为 `published`。
- `approved=false`：评论变为 `hidden`。

## 错误码

| code | 场景 |
|---|---|
| 40003 | 删除他人帖子或评论 |
| 40005 | 下单使用的种草来源帖不可用或未关联本次购买商品 |
| 40008 | 内容状态不允许操作 |
