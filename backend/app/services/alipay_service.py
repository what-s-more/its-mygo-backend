import asyncio
import base64
import json
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.models.order import Payment


class AlipayService:
    SUCCESS_TRADE_STATUS = {"TRADE_SUCCESS", "TRADE_FINISHED"}

    def is_configured(self) -> bool:
        return bool(
            settings.alipay_enabled
            and settings.alipay_app_id
            and settings.alipay_app_private_key
            and settings.alipay_public_key
        )

    async def precreate(self, db: AsyncSession, payment: Payment) -> str:
        self._ensure_configured()
        client, request_cls, model_cls = self._sdk_precreate_dependencies()
        request = request_cls()
        model = model_cls()
        model.out_trade_no = payment.payment_no
        model.total_amount = self._cent_to_yuan(payment.pay_amount_cent)
        model.subject = f"{settings.alipay_subject_prefix}-{payment.payment_no}"
        model.product_code = "FACE_TO_FACE_PAYMENT"
        request.biz_model = model
        if settings.alipay_notify_url:
            request.notify_url = settings.alipay_notify_url
        raw_response = await self._execute_request(client, request)
        response = self._loads_response(raw_response)
        result = self._extract_response_result(response, "alipay_trade_precreate_response")
        if result.get("code") != "10000" or not result.get("qr_code"):
            message = self._format_alipay_error(result, "支付宝预创建订单失败")
            raise AppException(40005, message)
        payment.channel = "alipay"
        payment.alipay_qr_code = result["qr_code"]
        await db.commit()
        await db.refresh(payment)
        return result["qr_code"]

    async def query(self, payment: Payment) -> dict[str, Any]:
        self._ensure_configured()
        client, request_cls, model_cls = self._sdk_query_dependencies()
        request = request_cls()
        model = model_cls()
        model.out_trade_no = payment.payment_no
        request.biz_model = model
        raw_response = await self._execute_request(client, request)
        response = self._loads_response(raw_response)
        result = self._extract_response_result(response, "alipay_trade_query_response")
        if result.get("code") != "10000" and result.get("sub_code") == "ACQ.TRADE_NOT_EXIST":
            return result
        if result.get("code") != "10000":
            message = self._format_alipay_error(result, "支付宝交易查询失败")
            raise AppException(40005, message)
        return result

    def parse_notify_body(self, raw_body: bytes) -> dict[str, str]:
        return dict(parse_qsl(raw_body.decode("utf-8"), keep_blank_values=True))

    def verify_notify(self, payload: dict[str, str]) -> bool:
        self._ensure_configured()
        sign = payload.get("sign")
        if not sign:
            return False
        sign_type = payload.get("sign_type", "RSA2")
        if sign_type != "RSA2":
            return False
        signed_content = "&".join(
            f"{key}={value}"
            for key, value in sorted(payload.items())
            if key not in {"sign", "sign_type"} and value != ""
        )
        public_key = self._load_public_key(settings.alipay_public_key or "")
        try:
            public_key.verify(
                base64.b64decode(sign),
                signed_content.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (ValueError, InvalidSignature):
            return False
        return True

    def _ensure_configured(self) -> None:
        if not self.is_configured():
            raise AppException(40005, "支付宝扫码支付未配置，请先在后端 .env 配置支付宝沙箱或正式环境参数")

    def _sdk_precreate_dependencies(self):
        try:
            from alipay.aop.api.AlipayClientConfig import AlipayClientConfig
            from alipay.aop.api.DefaultAlipayClient import DefaultAlipayClient
            from alipay.aop.api.domain.AlipayTradePrecreateModel import AlipayTradePrecreateModel
            from alipay.aop.api.request.AlipayTradePrecreateRequest import AlipayTradePrecreateRequest
        except ImportError as exc:
            raise AppException(40005, "缺少 alipay-sdk-python 依赖，请安装后再启用支付宝支付") from exc
        client = self._build_client(AlipayClientConfig, DefaultAlipayClient)
        return client, AlipayTradePrecreateRequest, AlipayTradePrecreateModel

    def _sdk_query_dependencies(self):
        try:
            from alipay.aop.api.AlipayClientConfig import AlipayClientConfig
            from alipay.aop.api.DefaultAlipayClient import DefaultAlipayClient
            from alipay.aop.api.domain.AlipayTradeQueryModel import AlipayTradeQueryModel
            from alipay.aop.api.request.AlipayTradeQueryRequest import AlipayTradeQueryRequest
        except ImportError as exc:
            raise AppException(40005, "缺少 alipay-sdk-python 依赖，请安装后再启用支付宝支付") from exc
        client = self._build_client(AlipayClientConfig, DefaultAlipayClient)
        return client, AlipayTradeQueryRequest, AlipayTradeQueryModel

    def _build_client(self, config_cls, client_cls):
        config = config_cls()
        config.server_url = settings.alipay_gateway_url
        config.app_id = settings.alipay_app_id
        config.app_private_key = settings.alipay_app_private_key
        config.alipay_public_key = settings.alipay_public_key
        config.charset = "utf-8"
        config.sign_type = "RSA2"
        return client_cls(alipay_client_config=config)

    def _loads_response(self, raw_response: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(raw_response, dict):
            return raw_response
        try:
            return json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise AppException(40005, "支付宝响应解析失败") from exc

    def _extract_response_result(self, response: dict[str, Any], key: str) -> dict[str, Any]:
        nested = response.get(key)
        if isinstance(nested, dict):
            return nested
        if "code" in response or "msg" in response or "sub_code" in response or "sub_msg" in response:
            return response
        return {}

    def _format_alipay_error(self, result: dict[str, Any], fallback: str) -> str:
        parts = [fallback]
        for key in ("code", "msg", "sub_code", "sub_msg"):
            value = result.get(key)
            if value:
                parts.append(f"{key}={value}")
        return "；".join(parts)

    def _cent_to_yuan(self, amount_cent: int) -> str:
        return f"{Decimal(amount_cent) / Decimal(100):.2f}"

    async def _execute_request(self, client: Any, request: Any) -> str | dict[str, Any]:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(client.execute, request),
                timeout=settings.alipay_request_timeout_seconds,
            )
        except TimeoutError as exc:
            raise AppException(
                40005,
                "支付宝沙箱网关请求超时，请检查本机网络、沙箱网关地址和后端 .env 支付宝配置",
            ) from exc
        except AppException:
            raise
        except Exception as exc:
            raise AppException(40005, f"支付宝沙箱网关请求失败：{self._safe_error_message(exc)}") from exc

    def _safe_error_message(self, exc: Exception) -> str:
        message = str(exc).strip() or exc.__class__.__name__
        return message[:300]

    def _load_public_key(self, public_key: str):
        stripped = public_key.strip()
        if not stripped.startswith("-----BEGIN PUBLIC KEY-----"):
            stripped = f"-----BEGIN PUBLIC KEY-----\n{stripped}\n-----END PUBLIC KEY-----"
        return serialization.load_pem_public_key(stripped.encode("utf-8"))


alipay_service = AlipayService()
