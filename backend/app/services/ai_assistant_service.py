import logging

import httpx

from app.core.config import settings
from app.schemas.ai_assistant import AiAssistantChatRequest, AiAssistantChatResponse

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是“一次买够（It's Mygo）”社交新零售电商平台的购物助手。
平台支持商品浏览、分类筛选、店铺主页、购物车、跨店订单、支付宝沙箱扫码支付、优惠券、满减、积分抵扣、拼团、社区种草、商品收藏、店铺关注、客服和售后。
回答要简洁、友好，只解释商城功能、购物流程、优惠规则和售后客服入口。不要承诺真实物流轨迹，不要代替用户执行下单、退款、改地址、改积分等关键操作。
"""


class AiAssistantService:
    async def chat(self, payload: AiAssistantChatRequest) -> AiAssistantChatResponse:
        message = payload.message.strip()
        if self._is_model_enabled():
            try:
                reply = await self._call_qwen(payload)
                if reply:
                    return AiAssistantChatResponse(reply=reply, provider=settings.ai_assistant_provider)
            except Exception as exc:  # noqa: BLE001 - AI assistant should degrade gracefully in local development.
                logger.warning("AI assistant model call failed, falling back to preset reply: %s", exc)
        reply = self._preset_reply(message)
        return AiAssistantChatResponse(reply=reply, provider="preset")

    def _is_model_enabled(self) -> bool:
        return bool(settings.ai_assistant_enabled and self._api_key())

    def _api_key(self) -> str | None:
        return settings.ai_assistant_api_key or settings.dashscope_api_key

    async def _call_qwen(self, payload: AiAssistantChatRequest) -> str:
        api_key = self._api_key()
        if not api_key:
            return ""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in payload.history[-10:]:
            role = item.get("role")
            content = item.get("content", "").strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content[:2000]})
        messages.append({"role": "user", "content": payload.message.strip()})
        url = f"{settings.ai_assistant_base_url.rstrip('/')}/chat/completions"
        request_body = {
            "model": settings.ai_assistant_model,
            "messages": messages,
            "stream": False,
            "extra_body": {"enable_thinking": settings.ai_assistant_enable_thinking},
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=settings.ai_assistant_request_timeout_seconds) as client:
            response = await client.post(url, json=request_body, headers=headers)
            response.raise_for_status()
            data = response.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        return str(message.get("content") or "").strip()

    def _preset_reply(self, message: str) -> str:
        text = message.lower()
        if any(keyword in message for keyword in ["拼团", "成团", "参团"]):
            return "拼团商品可以在“拼团专区”或商品详情页进入。拼团不加入购物车，不叠加满减或优惠券，但可以按平台规则使用积分抵扣。支付后等待成团，成团后订单会进入商家待发货。"
        if any(keyword in message for keyword in ["优惠", "优惠券", "满减", "积分", "会员"]):
            return "普通订单的优惠顺序是：商品金额先参与满减，再使用一张优惠券，最后按平台积分抵扣上限使用积分。拼团订单不叠加满减和优惠券，只支持积分抵扣。会员权益和积分规则以平台配置为准。"
        if any(keyword in message for keyword in ["售后", "退款", "退货"]):
            return "售后入口在订单详情页。你可以针对订单中的具体商品明细申请售后，支持按数量申请，例如买 2 件可以退 1 件；单件商品只做单件全额退款，不做部分退款。"
        if any(keyword in message for keyword in ["客服", "联系", "商家"]):
            return "商品详情页和订单详情页都可以联系商家客服；订单详情页也可以联系平台客服。进入会话后客服会先发送欢迎消息，你可以继续补充问题。"
        if any(keyword in message for keyword in ["支付", "支付宝", "二维码", "扫码"]):
            return "当前项目使用支付宝沙箱扫码支付。提交订单后会生成支付二维码，扫码完成后页面会同步支付状态；如果沙箱偶发延迟，可以稍等后刷新支付状态。"
        if any(keyword in message for keyword in ["地址", "收货", "发货", "物流"]):
            return "收货地址可以在用户中心维护，也可以在结算页新增。商家发货时会填写物流公司和单号，本项目不接入真实物流轨迹，收到商品后在订单详情页确认收货。"
        if any(keyword in message for keyword in ["社区", "种草", "帖子", "收藏"]):
            return "社区支持综合广场、种草专区、商家动态和体验分享。用户可收藏帖子；从种草帖进入商品并加购后，购物车会记录种草来源，确认收货后会按规则给推广人和下单者发放积分奖励。"
        if any(keyword in text for keyword in ["hello", "hi"]) or any(keyword in message for keyword in ["你好", "您好"]):
            return "你好，我是一次买够的 AI 购物助手。你可以问我购物流程、优惠积分、拼团、售后、客服、社区种草等问题。"
        return f"{SYSTEM_PROMPT}\n\n针对你的问题，我建议先从商城顶部导航进入对应页面：商品和分类在首页，拼团在拼团专区，订单和售后在订单详情，优惠券、地址和收藏在个人中心。如果你愿意，可以把问题描述得更具体一些。"


ai_assistant_service = AiAssistantService()
