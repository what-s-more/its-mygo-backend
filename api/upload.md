# 上传接口

## 当前实现范围

- 已实现本地图片上传，文件保存到后端 `uploads` 目录，可用于商品图、帖子图、用户头像等图片场景。
- 上传成功后返回 `/static/uploads/{filename}`，FastAPI 会以静态资源方式暴露。
- 当前接口暂未强制登录，后续接入头像、商品图、评价图时可按场景增加鉴权。

## POST `/upload/image`

上传图片文件，返回可访问地址。

### 请求

- `multipart/form-data`
- 字段：`file`

### 响应

```json
{ "code": 0, "message": "ok", "data": { "url": "/static/uploads/xxx.jpg" } }
```

## 约束

- 校验 MIME 类型
- 校验文件大小
- 文件名需随机化
- 默认支持：`image/jpeg`、`image/png`、`image/webp`
- 单文件大小建议限制为 5MB
- 用户端上传用于头像、评价、社区图片；管理端上传用于商品、店铺、活动图片

## 错误码

| code | 场景 |
|---|---|
| 40009 | 文件类型、大小或内容不合法 |
| 50000 | 保存失败 |
