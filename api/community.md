# 社区

## 统一说明

- 帖子支持 `normal`、`grass`、`merchant_ad`。
- 当前规则为发布后展示：帖子和评论创建后默认 `published`，平台通过隐藏操作进行内容治理。
- 管理端保留内容管理能力，可查询公开/隐藏内容，并对帖子、评论执行隐藏。
- 商家端和平台端可以通过管理端社区接口浏览完整帖子内容和评论；商家端可发布商家动态。
- 订单可通过 `source_post_id` 记录种草来源；买家确认收货后，系统给种草帖作者和下单者分别增加积分奖励。
- 社区分区字段为 `section`，当前支持 `square`、`grass`、`merchant`、`help`、`experience`。
- 综合广场 `square` 是总入口：查询不传 `section` 或传 `section=square` 时展示所有公开帖子，不按分区过滤。未指定分区的帖子默认属于 `square`。
- 种草专区 `grass` 只展示种草分区或种草类型帖子。
- 已实现基础话题：帖子可带 `topic_tags`，用户端可查看热门话题并按话题筛选帖子。
- 已实现社区用户主页：可查看作者摘要、公开发帖统计、种草帖数、评论数、获赞数和近期帖子。
- 后续如继续深化社区治理，可扩展话题后台合并/删除、用户主页隐私设置和更细的商家动态权限配置。

## 帖子接口

- `GET /community/posts`
- `GET /community/posts/{id}`
- `POST /community/posts`
- `DELETE /community/posts/{id}`
- `POST /community/posts/{id}/like`
- `GET /community/posts/{id}/comments`
- `POST /community/posts/{id}/comments`
- `GET /community/topics`
- `GET /community/users/{user_id}`
- `GET /community/users/{user_id}/posts`
- 管理端：`GET /admin/community/posts`
- 管理端：`POST /admin/community/posts`
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
  "section": "grass",
  "image_urls": ["/static/uploads/a.jpg"],
  "product_ids": [1],
  "topic_tags": ["零食测评"]
}
```

种草帖 `type=grass` 必须关联至少一个 `product_ids`，且这些商品必须来自发帖用户已完成订单。普通帖和商家动态可以绑定商品，但不产生种草奖励。前端页面应通过商品选择器生成 `product_ids`，不要要求用户手动输入商品 ID；用户端发帖已使用“搜索商品 + 商品卡片勾选 + 已选商品标签”的方式选择关联商品。

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
- 买家确认收货后，系统给种草帖作者和下单者分别增加积分奖励。
- 奖励按来源帖关联且本次购买命中的商品原价计算：`sum(unit_price_cent * quantity) * 1%`，向下取整为积分；不按实付价计算，多买多得。
- 拼团订单不参与社区种草奖励。
- 奖励通过统一积分服务写入 `points_log`，并按订单去重。

## 帖子字段

| 字段 | 类型 | 说明 |
|---|---|---|
| id | number | 帖子 ID |
| type | string | normal/grass/merchant_ad |
| section | string | square/grass/merchant/help/experience |
| status | string | published/hidden |
| author | object | 作者摘要 |
| product_ids | array | 关联商品 ID |
| topic_tags | array | 话题标签 |
| like_count | number | 点赞数 |
| comment_count | number | 评论数 |

## GET `/community/posts`

查询公开帖子。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| section | string | 否 | `square` 或空表示综合广场；也可传 `grass/merchant/help/experience` |
| author_id | number | 否 | 只看某个作者的公开帖子 |
| topic | string | 否 | 按话题标签精确筛选，例如 `开箱` |
| page | number | 否 | 页码 |
| page_size | number | 否 | 每页数量 |

## GET `/community/topics`

获取热门话题，按公开帖子引用次数倒序返回。

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    { "name": "开箱", "post_count": 3 }
  ]
}
```

## GET `/community/users/{user_id}`

获取社区作者主页。

响应核心字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| user | object | 作者摘要 |
| post_count | number | 公开帖子数 |
| grass_post_count | number | 公开种草帖数 |
| comment_count | number | 公开评论数 |
| like_received_count | number | 公开帖子收到的点赞数 |
| recent_posts | array | 最近公开帖子 |

## GET `/community/users/{user_id}/posts`

分页查看某个作者的公开帖子。支持 `section`、`topic`、`page`、`page_size`。

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

查询帖子列表。默认查询公开帖子，平台和商家端均可用于完整浏览社区内容；平台端额外展示隐藏帖子/隐藏评论治理操作。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| status | string | 否 | 默认 `published`，可选 `published`、`hidden` |
| section | string | 否 | `square` 或空表示综合广场展示全部；`grass/merchant/help/experience` 表示分区筛选 |
| page | number | 否 | 页码，默认 1 |
| page_size | number | 否 | 每页数量，默认 20 |

### POST `/admin/community/posts`

后台账号发布社区内容。当前用于商家端发布商家动态，也允许平台账号发布普通管理内容。

```json
{
  "type": "merchant_ad",
  "section": "merchant",
  "title": "新品上架",
  "content": "本店新品已上架",
  "image_urls": ["/static/uploads/a.jpg"],
  "product_ids": [1],
  "topic_tags": ["新品"]
}
```

规则：

- 仅 `platform_operator` 和 `merchant_operator` 可调用。
- 商家账号调用时，后端强制 `type=merchant_ad`、`section=merchant`，避免商家伪装普通用户种草。
- 后台账号发帖会自动创建或复用一个后台账号对应的系统用户作为社区作者，不改动社区帖子表结构。
- 商家动态可绑定商品，但不触发种草奖励。

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
