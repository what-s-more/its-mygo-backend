import json
from datetime import UTC, datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ForbiddenException
from app.models.customer_service import CustomerServiceConversation, CustomerServiceMessage
from app.models.order import Order
from app.models.product import Merchant, Product
from app.models.user import AdminUser, User
from app.schemas.customer_service import (
    CustomerServiceConversationCreateRequest,
    CustomerServiceConversationResponse,
    CustomerServiceMessageCreateRequest,
    CustomerServiceMessageResponse,
)
from app.websocket.manager import websocket_manager


class CustomerServiceService:
    async def create_or_get_conversation(
        self,
        db: AsyncSession,
        user: User,
        payload: CustomerServiceConversationCreateRequest,
    ) -> CustomerServiceConversationResponse:
        merchant_id = await self._resolve_user_merchant_id(db, user, payload)
        product_id = await self._resolve_product_id(db, merchant_id, payload.product_id)
        order_id = await self._resolve_order_id(db, user, merchant_id, payload.order_id)
        result = await db.execute(
            select(CustomerServiceConversation).where(
                CustomerServiceConversation.user_id == user.id,
                CustomerServiceConversation.target_type == payload.target_type,
                CustomerServiceConversation.merchant_id.is_(None)
                if merchant_id is None
                else CustomerServiceConversation.merchant_id == merchant_id,
                CustomerServiceConversation.product_id.is_(None)
                if product_id is None
                else CustomerServiceConversation.product_id == product_id,
                CustomerServiceConversation.order_id.is_(None)
                if order_id is None
                else CustomerServiceConversation.order_id == order_id,
                CustomerServiceConversation.status == "open",
            )
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            conversation = CustomerServiceConversation(
                user_id=user.id,
                target_type=payload.target_type,
                merchant_id=merchant_id,
                product_id=product_id,
                order_id=order_id,
                status="open",
            )
            db.add(conversation)
            await db.flush()
            await self._create_auto_reply(db, conversation)
        if payload.initial_message and payload.initial_message.strip():
            await self._create_message(
                db,
                conversation,
                sender_type="user",
                sender_id=user.id,
                payload=CustomerServiceMessageCreateRequest(content=payload.initial_message.strip()),
            )
        await db.commit()
        await db.refresh(conversation)
        return await self._conversation_to_response(db, conversation, viewer_type="user", viewer_id=user.id)

    async def list_user_conversations(
        self,
        db: AsyncSession,
        user: User,
        *,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[CustomerServiceConversationResponse], int]:
        statement = select(CustomerServiceConversation).where(CustomerServiceConversation.user_id == user.id)
        if status:
            statement = statement.where(CustomerServiceConversation.status == status)
        return await self._paginate_conversations(db, statement, "user", user.id, page, page_size)

    async def list_admin_conversations(
        self,
        db: AsyncSession,
        admin: AdminUser,
        *,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[CustomerServiceConversationResponse], int]:
        statement = select(CustomerServiceConversation)
        if admin.role == "merchant_operator":
            if admin.merchant_id is None:
                raise ForbiddenException("商家运营未绑定店铺")
            statement = statement.where(
                CustomerServiceConversation.target_type == "merchant",
                CustomerServiceConversation.merchant_id == admin.merchant_id,
            )
            viewer_type = "merchant"
        elif admin.role == "platform_operator":
            statement = statement.where(CustomerServiceConversation.target_type == "platform")
            viewer_type = "platform"
        else:
            raise ForbiddenException("当前账号无客服权限")
        if status:
            statement = statement.where(CustomerServiceConversation.status == status)
        return await self._paginate_conversations(db, statement, viewer_type, admin.id, page, page_size)

    async def list_messages(
        self,
        db: AsyncSession,
        conversation_id: int,
        *,
        user: User | None = None,
        admin: AdminUser | None = None,
        page: int,
        page_size: int,
    ) -> tuple[list[CustomerServiceMessageResponse], int]:
        conversation = await self._get_authorized_conversation(db, conversation_id, user=user, admin=admin)
        viewer_type, viewer_id = self._viewer_identity(user=user, admin=admin, conversation=conversation)
        await self.mark_read(db, conversation, viewer_type)
        statement = (
            select(CustomerServiceMessage)
            .where(CustomerServiceMessage.conversation_id == conversation.id)
            .order_by(CustomerServiceMessage.created_at.asc(), CustomerServiceMessage.id.asc())
        )
        all_result = await db.execute(statement)
        all_messages = list(all_result.scalars())
        result = await db.execute(statement.offset((page - 1) * page_size).limit(page_size))
        messages = list(result.scalars())
        await db.commit()
        return [await self._message_to_response(db, message) for message in messages], len(all_messages)

    async def send_user_message(
        self,
        db: AsyncSession,
        user: User,
        conversation_id: int,
        payload: CustomerServiceMessageCreateRequest,
    ) -> CustomerServiceMessageResponse:
        conversation = await self._get_authorized_conversation(db, conversation_id, user=user)
        if conversation.status != "open":
            raise AppException(40008, "会话已关闭，不能继续发送消息")
        message = await self._create_message(db, conversation, sender_type="user", sender_id=user.id, payload=payload)
        await db.commit()
        response = await self._message_to_response(db, message)
        await websocket_manager.broadcast(self._channel(conversation.id), {"type": "chat.message", "data": response.model_dump(mode="json")})
        return response

    async def send_admin_message(
        self,
        db: AsyncSession,
        admin: AdminUser,
        conversation_id: int,
        payload: CustomerServiceMessageCreateRequest,
    ) -> CustomerServiceMessageResponse:
        conversation = await self._get_authorized_conversation(db, conversation_id, admin=admin)
        if conversation.status != "open":
            raise AppException(40008, "会话已关闭，不能继续发送消息")
        sender_type = "merchant" if admin.role == "merchant_operator" else "platform"
        message = await self._create_message(db, conversation, sender_type=sender_type, sender_id=admin.id, payload=payload)
        await db.commit()
        response = await self._message_to_response(db, message)
        await websocket_manager.broadcast(self._channel(conversation.id), {"type": "chat.message", "data": response.model_dump(mode="json")})
        return response

    async def delete_user_conversation(self, db: AsyncSession, user: User, conversation_id: int) -> None:
        """用户删除自己的客服会话（物理删除会话及其所有消息）。"""
        conversation = await self._get_authorized_conversation(db, conversation_id, user=user)
        # 先删除会话下的所有消息，再删除会话本身
        result = await db.execute(
            select(CustomerServiceMessage).where(CustomerServiceMessage.conversation_id == conversation.id)
        )
        for message in result.scalars():
            await db.delete(message)
        await db.delete(conversation)
        await db.commit()
        await websocket_manager.broadcast(
            self._channel(conversation.id),
            {"type": "conversation.deleted", "conversation_id": conversation.id},
        )

    async def close_conversation(self, db: AsyncSession, admin: AdminUser, conversation_id: int) -> CustomerServiceConversationResponse:
        conversation = await self._get_authorized_conversation(db, conversation_id, admin=admin)
        conversation.status = "closed"
        await db.commit()
        await websocket_manager.broadcast(self._channel(conversation.id), {"type": "conversation.closed", "conversation_id": conversation.id})
        viewer_type = "merchant" if admin.role == "merchant_operator" else "platform"
        return await self._conversation_to_response(db, conversation, viewer_type=viewer_type, viewer_id=admin.id)

    async def mark_read(self, db: AsyncSession, conversation: CustomerServiceConversation, viewer_type: str) -> None:
        result = await db.execute(
            select(CustomerServiceMessage).where(
                CustomerServiceMessage.conversation_id == conversation.id,
                CustomerServiceMessage.is_read.is_(False),
                CustomerServiceMessage.sender_type != viewer_type,
            )
        )
        for message in result.scalars():
            message.is_read = True

    async def _paginate_conversations(
        self,
        db: AsyncSession,
        statement: Select,
        viewer_type: str,
        viewer_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[CustomerServiceConversationResponse], int]:
        statement = statement.order_by(
            CustomerServiceConversation.last_message_at.is_(None),
            CustomerServiceConversation.last_message_at.desc(),
            CustomerServiceConversation.updated_at.desc(),
        )
        all_result = await db.execute(statement)
        all_conversations = list(all_result.scalars())
        result = await db.execute(statement.offset((page - 1) * page_size).limit(page_size))
        conversations = list(result.scalars())
        return [
            await self._conversation_to_response(db, conversation, viewer_type=viewer_type, viewer_id=viewer_id)
            for conversation in conversations
        ], len(all_conversations)

    async def _create_message(
        self,
        db: AsyncSession,
        conversation: CustomerServiceConversation,
        *,
        sender_type: str,
        sender_id: int,
        payload: CustomerServiceMessageCreateRequest,
    ) -> CustomerServiceMessage:
        now = datetime.now(UTC)
        message = CustomerServiceMessage(
            conversation_id=conversation.id,
            sender_type=sender_type,
            sender_id=sender_id,
            content_type=payload.content_type,
            content=payload.content.strip(),
            image_urls=json.dumps(payload.image_urls, ensure_ascii=False),
            is_read=False,
        )
        conversation.last_message_at = now
        db.add(message)
        await db.flush()
        await db.refresh(message)
        return message

    async def _create_auto_reply(self, db: AsyncSession, conversation: CustomerServiceConversation) -> None:
        if conversation.target_type == "platform":
            content = "您好，我是“一次买够”平台的客服！请问有什么能帮到您的？"
            sender_type = "platform"
        else:
            merchant = await db.get(Merchant, conversation.merchant_id) if conversation.merchant_id else None
            merchant_name = merchant.name if merchant else "本店"
            content = f"您好，我是“{merchant_name}”的客服！请问有什么能帮到您的？"
            sender_type = "merchant"
        await self._create_message(
            db,
            conversation,
            sender_type=sender_type,
            sender_id=0,
            payload=CustomerServiceMessageCreateRequest(content=content),
        )

    async def _resolve_user_merchant_id(
        self,
        db: AsyncSession,
        user: User,
        payload: CustomerServiceConversationCreateRequest,
    ) -> int | None:
        if payload.target_type == "platform":
            return None
        merchant = await db.get(Merchant, payload.merchant_id)
        if merchant is None or not merchant.is_active:
            raise AppException(40004, "客服店铺不存在或不可用", 404)
        if payload.order_id is not None:
            order = await db.get(Order, payload.order_id)
            if order is None or order.user_id != user.id or order.merchant_id != merchant.id:
                raise AppException(40003, "订单不属于该店铺或当前用户")
        return merchant.id

    async def _resolve_product_id(self, db: AsyncSession, merchant_id: int | None, product_id: int | None) -> int | None:
        if product_id is None:
            return None
        product = await db.get(Product, product_id)
        if product is None:
            raise AppException(40004, "商品不存在", 404)
        if merchant_id is not None and product.merchant_id != merchant_id:
            raise AppException(40003, "商品不属于该店铺")
        return product.id

    async def _resolve_order_id(
        self,
        db: AsyncSession,
        user: User,
        merchant_id: int | None,
        order_id: int | None,
    ) -> int | None:
        if order_id is None:
            return None
        order = await db.get(Order, order_id)
        if order is None or order.user_id != user.id:
            raise AppException(40004, "订单不存在", 404)
        if merchant_id is not None and order.merchant_id != merchant_id:
            raise AppException(40003, "订单不属于该店铺")
        return order.id

    async def _get_authorized_conversation(
        self,
        db: AsyncSession,
        conversation_id: int,
        *,
        user: User | None = None,
        admin: AdminUser | None = None,
    ) -> CustomerServiceConversation:
        conversation = await db.get(CustomerServiceConversation, conversation_id)
        if conversation is None:
            raise AppException(40004, "客服会话不存在", 404)
        if user is not None:
            if conversation.user_id != user.id:
                raise ForbiddenException()
            return conversation
        if admin is not None:
            if admin.role == "merchant_operator":
                if conversation.target_type != "merchant" or conversation.merchant_id != admin.merchant_id:
                    raise ForbiddenException("商家只能处理本店客服会话")
                return conversation
            if admin.role == "platform_operator":
                if conversation.target_type != "platform":
                    raise ForbiddenException("平台客服不能查看或处理商家会话")
                return conversation
        raise ForbiddenException()

    def _viewer_identity(
        self,
        *,
        user: User | None,
        admin: AdminUser | None,
        conversation: CustomerServiceConversation,
    ) -> tuple[str, int]:
        if user is not None:
            return "user", user.id
        if admin is not None and admin.role == "merchant_operator":
            return "merchant", admin.id
        if admin is not None and admin.role == "platform_operator":
            return "platform", admin.id
        raise ForbiddenException()

    async def _conversation_to_response(
        self,
        db: AsyncSession,
        conversation: CustomerServiceConversation,
        *,
        viewer_type: str,
        viewer_id: int,
    ) -> CustomerServiceConversationResponse:
        user = await db.get(User, conversation.user_id)
        merchant = await db.get(Merchant, conversation.merchant_id) if conversation.merchant_id else None
        product = await db.get(Product, conversation.product_id) if conversation.product_id else None
        order = await db.get(Order, conversation.order_id) if conversation.order_id else None
        last_message = await self._last_message(db, conversation.id)
        unread_count = await db.scalar(
            select(func.count(CustomerServiceMessage.id)).where(
                CustomerServiceMessage.conversation_id == conversation.id,
                CustomerServiceMessage.is_read.is_(False),
                CustomerServiceMessage.sender_type != viewer_type,
            )
        ) or 0
        return CustomerServiceConversationResponse(
            id=conversation.id,
            user_id=conversation.user_id,
            user_nickname=user.nickname if user else None,
            target_type=conversation.target_type,
            merchant_id=conversation.merchant_id,
            merchant_name=merchant.name if merchant else None,
            product_id=conversation.product_id,
            product_name=product.name if product else None,
            order_id=conversation.order_id,
            order_no=order.order_no if order else None,
            status=conversation.status,
            last_message_at=conversation.last_message_at,
            last_message=last_message.content if last_message else None,
            unread_count=int(unread_count),
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )

    async def _message_to_response(self, db: AsyncSession, message: CustomerServiceMessage) -> CustomerServiceMessageResponse:
        sender_name = None
        if message.sender_type == "user":
            user = await db.get(User, message.sender_id)
            sender_name = user.nickname if user else None
        elif message.sender_id == 0:
            if message.sender_type == "platform":
                sender_name = "一次买够平台客服"
            else:
                conversation = await db.get(CustomerServiceConversation, message.conversation_id)
                merchant = await db.get(Merchant, conversation.merchant_id) if conversation and conversation.merchant_id else None
                sender_name = f"{merchant.name}客服" if merchant else "商家客服"
        else:
            admin = await db.get(AdminUser, message.sender_id)
            sender_name = admin.real_name if admin else None
        return CustomerServiceMessageResponse(
            id=message.id,
            conversation_id=message.conversation_id,
            sender_type=message.sender_type,
            sender_id=message.sender_id,
            sender_name=sender_name,
            content_type=message.content_type,
            content=message.content,
            image_urls=json.loads(message.image_urls or "[]"),
            is_read=message.is_read,
            created_at=message.created_at,
        )

    async def _last_message(self, db: AsyncSession, conversation_id: int) -> CustomerServiceMessage | None:
        result = await db.execute(
            select(CustomerServiceMessage)
            .where(CustomerServiceMessage.conversation_id == conversation_id)
            .order_by(CustomerServiceMessage.created_at.desc(), CustomerServiceMessage.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    def _channel(self, conversation_id: int) -> str:
        return f"customer_service:{conversation_id}"


customer_service = CustomerServiceService()
