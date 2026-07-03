import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.exceptions import AppException, ForbiddenException
from app.models.community import CommunityPost, GrassConversionReward
from app.models.order import CartItem, Order, OrderItem, Payment, ProductReview, Refund
from app.models.product import Product, Sku
from app.models.user import User, UserAddress
from app.schemas.order import (
    CartAddRequest,
    CartItemResponse,
    CartUpdateRequest,
    CheckoutItemRequest,
    CheckoutRequest,
    CheckoutResponse,
    CreateOrderRequest,
    CreateOrderResponse,
    OrderItemResponse,
    OrderResponse,
    PaymentResponse,
    RefundCreateRequest,
    RefundResponse,
    ReviewCreateRequest,
    ReviewResponse,
    ShipOrderRequest,
    ShippingAddressSnapshot,
)
from app.services.address_service import address_service
from app.services.inventory_service import inventory_service
from app.services.points_service import points_service
from app.services.promotion_service import promotion_service


class OrderService:
    GRASS_REWARD_POINTS = 10

    async def list_cart(self, db: AsyncSession, user: User) -> list[CartItemResponse]:
        result = await db.execute(
            select(CartItem)
            .where(CartItem.user_id == user.id)
            .order_by(CartItem.updated_at.desc())
        )
        cart_items = list(result.scalars())
        return [await self._cart_item_to_response(db, item) for item in cart_items]

    async def add_cart_item(self, db: AsyncSession, user: User, payload: CartAddRequest) -> list[CartItemResponse]:
        sku = await self._get_sku(db, payload.sku_id)
        if sku.product.status != "on_sale":
            raise AppException(40005, "商品未上架")
        if sku.stock < payload.quantity:
            raise AppException(40007, "库存不足")

        result = await db.execute(
            select(CartItem).where(CartItem.user_id == user.id, CartItem.sku_id == payload.sku_id)
        )
        cart_item = result.scalar_one_or_none()
        if cart_item is None:
            db.add(CartItem(user_id=user.id, sku_id=payload.sku_id, quantity=payload.quantity, checked=True))
        else:
            cart_item.quantity += payload.quantity
            cart_item.checked = True
        await db.commit()
        return await self.list_cart(db, user)

    async def update_cart_item(
        self,
        db: AsyncSession,
        user: User,
        sku_id: int,
        payload: CartUpdateRequest,
    ) -> list[CartItemResponse]:
        cart_item = await self._get_cart_item(db, user.id, sku_id)
        cart_item.quantity = payload.quantity
        cart_item.checked = payload.checked
        await db.commit()
        return await self.list_cart(db, user)

    async def delete_cart_item(self, db: AsyncSession, user: User, sku_id: int) -> list[CartItemResponse]:
        await db.execute(delete(CartItem).where(CartItem.user_id == user.id, CartItem.sku_id == sku_id))
        await db.commit()
        return await self.list_cart(db, user)

    async def checkout(self, db: AsyncSession, user: User, payload: CheckoutRequest) -> CheckoutResponse:
        items = await self._resolve_checkout_items(db, user, payload.items)
        cart_items = [await self._sku_quantity_to_cart_response(db, item.sku_id, item.quantity) for item in items]
        sku_quantities = []
        for item in items:
            sku = await self._get_sku(db, item.sku_id)
            if sku.product.status == "on_sale" and sku.stock >= item.quantity:
                sku_quantities.append((sku, item.quantity))
        total_amount = sum(item.price_cent * item.quantity for item in cart_items if item.invalid_reason is None)
        discount_amount, _ = await promotion_service.calculate_coupon_discount(
            db,
            user,
            payload.coupon_id,
            total_amount,
            sku_quantities,
        )
        addresses = await address_service.list_addresses(db, user)
        return CheckoutResponse(
            items=cart_items,
            addresses=addresses,
            total_amount_cent=total_amount,
            discount_amount_cent=discount_amount,
            pay_amount_cent=total_amount - discount_amount,
        )

    async def create_order(self, db: AsyncSession, user: User, payload: CreateOrderRequest) -> CreateOrderResponse:
        existing_result = await db.execute(
            select(Order)
            .where(Order.user_id == user.id, Order.client_order_token == payload.client_order_token)
            .options(selectinload(Order.payment))
        )
        existing_orders = list(existing_result.scalars().unique())
        if existing_orders:
            payment = existing_orders[0].payment
            return CreateOrderResponse(
                payment_id=payment.id,
                payment_no=payment.payment_no,
                order_ids=[order.id for order in existing_orders],
                pay_amount_cent=payment.pay_amount_cent,
                expire_at=None,
            )

        items = await self._resolve_checkout_items(db, user, payload.items)
        if not items:
            raise AppException(40001, "请选择要购买的商品")
        address_snapshot = None
        if payload.shipping_address_id is not None:
            address = await address_service.get_owned_address(db, user, payload.shipping_address_id)
            address_snapshot = self._address_to_snapshot(address)

        sku_quantities = []
        for item in items:
            sku = await self._get_sku(db, item.sku_id)
            if sku.product.status != "on_sale":
                raise AppException(40005, "商品未上架")
            if sku.stock < item.quantity:
                raise AppException(40007, "库存不足")
            sku_quantities.append((sku, item.quantity))
        source_post = None
        source_product_ids: set[int] = set()
        if payload.source_post_id is not None:
            source_post, source_product_ids = await self._validate_source_post(
                db,
                user,
                payload.source_post_id,
                {sku.product_id for sku, _ in sku_quantities},
            )

        total_amount = sum(sku.price_cent * quantity for sku, quantity in sku_quantities)
        discount_amount, user_coupon = await promotion_service.calculate_coupon_discount(
            db,
            user,
            payload.coupon_id,
            total_amount,
            sku_quantities,
        )
        pay_amount = total_amount - discount_amount
        payment = Payment(
            payment_no=f"PAY{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}{uuid4().hex[:8]}",
            user_id=user.id,
            pay_amount_cent=pay_amount,
        )
        db.add(payment)
        await db.flush()

        orders_by_merchant: dict[int, list[tuple[Sku, int]]] = {}
        for sku, quantity in sku_quantities:
            orders_by_merchant.setdefault(sku.product.merchant_id, []).append((sku, quantity))

        orders: list[Order] = []
        discount_by_merchant = promotion_service.allocate_discount_by_merchant(
            discount_amount,
            user_coupon,
            sku_quantities,
        )
        for merchant_id, merchant_items in orders_by_merchant.items():
            order_amount = sum(sku.price_cent * quantity for sku, quantity in merchant_items)
            order_discount = min(order_amount, discount_by_merchant.get(merchant_id, 0))
            order = Order(
                order_no=f"ORD{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}{uuid4().hex[:8]}",
                payment_id=payment.id,
                user_id=user.id,
                merchant_id=merchant_id,
                status="pending_payment",
                total_amount_cent=order_amount,
                pay_amount_cent=order_amount - order_discount,
                client_order_token=payload.client_order_token,
                source_post_id=source_post.id
                if source_post is not None and any(sku.product_id in source_product_ids for sku, _ in merchant_items)
                else None,
                source_user_id=source_post.user_id
                if source_post is not None and any(sku.product_id in source_product_ids for sku, _ in merchant_items)
                else None,
                shipping_address_snapshot=json.dumps(address_snapshot, ensure_ascii=False) if address_snapshot else None,
            )
            order.items = [
                OrderItem(
                    product_id=sku.product_id,
                    sku_id=sku.id,
                    product_name=sku.product.name,
                    sku_name=sku.name,
                    unit_price_cent=sku.price_cent,
                    quantity=quantity,
                    total_amount_cent=sku.price_cent * quantity,
                )
                for sku, quantity in merchant_items
            ]
            orders.append(order)
            db.add(order)
            for sku, quantity in merchant_items:
                await inventory_service.change_stock(
                    db,
                    sku,
                    change_quantity=-quantity,
                    change_type="order_lock",
                    remark=f"创建订单扣减库存：{order.order_no}",
                )

        await db.flush()
        await promotion_service.mark_coupon_used(db, user_coupon, orders[0].id if orders else None)
        if payload.items is None:
            await db.execute(delete(CartItem).where(CartItem.user_id == user.id, CartItem.checked.is_(True)))
        await db.commit()
        for order in orders:
            await db.refresh(order)
        return CreateOrderResponse(
            payment_id=payment.id,
            payment_no=payment.payment_no,
            order_ids=[order.id for order in orders],
            pay_amount_cent=payment.pay_amount_cent,
            expire_at=(datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
        )

    async def list_orders(
        self,
        db: AsyncSession,
        user: User,
        *,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[OrderResponse], int]:
        statement = (
            select(Order)
            .where(Order.user_id == user.id)
            .options(selectinload(Order.items))
            .order_by(Order.created_at.desc())
        )
        if status:
            statement = statement.where(Order.status == status)
        total_result = await db.execute(statement)
        all_orders = list(total_result.scalars().unique())
        result = await db.execute(statement.offset((page - 1) * page_size).limit(page_size))
        orders = list(result.scalars().unique())
        return [self.to_order_response(order) for order in orders], len(all_orders)

    async def get_order(self, db: AsyncSession, user: User, order_id: int) -> OrderResponse:
        order = await self._get_order(db, order_id)
        if order.user_id != user.id:
            raise ForbiddenException()
        return self.to_order_response(order)

    async def cancel_order(self, db: AsyncSession, user: User, order_id: int) -> OrderResponse:
        order = await self._get_order(db, order_id)
        if order.user_id != user.id:
            raise ForbiddenException()
        if order.status != "pending_payment":
            raise AppException(40008, "当前订单状态不允许取消")
        await self._cancel_pending_order(db, order)
        await db.commit()
        return await self.get_order(db, user, order_id)

    async def confirm_order(self, db: AsyncSession, user: User, order_id: int) -> OrderResponse:
        order = await self._get_order(db, order_id)
        if order.user_id != user.id:
            raise ForbiddenException()
        if order.status not in {"shipping", "pending_receipt"}:
            raise AppException(40008, "当前订单状态不允许确认收货")
        order.status = "completed"
        order.received_at = datetime.now(UTC)
        await self._reward_grass_conversion(db, order)
        await db.commit()
        return await self.get_order(db, user, order_id)

    async def ship_order(self, db: AsyncSession, order_id: int, payload: ShipOrderRequest) -> OrderResponse:
        order = await self._get_order(db, order_id)
        if order.status != "pending_shipment":
            raise AppException(40008, "当前订单状态不允许发货")
        order.status = "shipping"
        order.logistics_company = payload.logistics_company
        order.tracking_no = payload.tracking_no
        order.shipped_at = datetime.now(UTC)
        await db.commit()
        return self.to_order_response(order)

    async def create_review(
        self,
        db: AsyncSession,
        user: User,
        order_id: int,
        payload: ReviewCreateRequest,
    ) -> ReviewResponse:
        order = await self._get_order(db, order_id)
        if order.user_id != user.id:
            raise ForbiddenException()
        if order.status != "completed":
            raise AppException(40008, "订单完成后才能评价")
        if payload.product_id not in {item.product_id for item in order.items}:
            raise AppException(40005, "只能评价本订单商品")
        existing_result = await db.execute(
            select(ProductReview).where(
                ProductReview.user_id == user.id,
                ProductReview.order_id == order_id,
                ProductReview.product_id == payload.product_id,
            )
        )
        if existing_result.scalar_one_or_none() is not None:
            raise AppException(40005, "该商品已评价")
        review = ProductReview(
            user_id=user.id,
            order_id=order_id,
            product_id=payload.product_id,
            score=payload.score,
            content=payload.content,
            image_urls=json.dumps(payload.image_urls, ensure_ascii=False),
            status="published",
        )
        db.add(review)
        await db.commit()
        await db.refresh(review)
        return self._review_to_response(review)

    async def list_product_reviews(
        self,
        db: AsyncSession,
        product_id: int,
        *,
        page: int,
        page_size: int,
        include_pending: bool = False,
    ) -> tuple[list[ReviewResponse], int]:
        statement = select(ProductReview).where(ProductReview.product_id == product_id)
        if not include_pending:
            statement = statement.where(ProductReview.status == "published")
        statement = statement.order_by(ProductReview.created_at.desc())
        all_result = await db.execute(statement)
        all_reviews = list(all_result.scalars())
        result = await db.execute(statement.offset((page - 1) * page_size).limit(page_size))
        return [self._review_to_response(review) for review in result.scalars()], len(all_reviews)

    async def audit_review(self, db: AsyncSession, review_id: int, approved: bool) -> ReviewResponse:
        review = await db.get(ProductReview, review_id)
        if review is None:
            raise AppException(40004, "评价不存在", 404)
        review.status = "published" if approved else "hidden"
        await db.commit()
        await db.refresh(review)
        return self._review_to_response(review)

    async def create_refund(
        self,
        db: AsyncSession,
        user: User,
        order_id: int,
        payload: RefundCreateRequest,
    ) -> RefundResponse:
        order = await self._get_order(db, order_id)
        if order.user_id != user.id:
            raise ForbiddenException()
        if order.status not in {"pending_receipt", "shipping", "completed"}:
            raise AppException(40008, "当前订单状态不允许申请售后")
        existing_result = await db.execute(
            select(Refund).where(Refund.order_id == order_id, Refund.status.in_(["pending_approval", "approved"]))
        )
        if existing_result.scalar_one_or_none() is not None:
            raise AppException(40005, "该订单已有处理中售后")
        refund_amount = payload.refund_amount_cent if payload.refund_amount_cent is not None else order.pay_amount_cent
        if refund_amount > order.pay_amount_cent:
            raise AppException(40001, "退款金额不能超过订单实付金额")
        refund = Refund(
            order_id=order_id,
            user_id=user.id,
            refund_amount_cent=refund_amount,
            reason_type=payload.reason_type,
            reason=payload.reason,
            status="pending_approval",
            origin_order_status=order.status,
        )
        order.status = "after_sale"
        db.add(refund)
        await db.commit()
        await db.refresh(refund)
        return RefundResponse.model_validate(refund)

    async def list_refunds(self, db: AsyncSession, *, page: int, page_size: int) -> tuple[list[RefundResponse], int]:
        statement = select(Refund).order_by(Refund.created_at.desc())
        all_result = await db.execute(statement)
        all_refunds = list(all_result.scalars())
        result = await db.execute(statement.offset((page - 1) * page_size).limit(page_size))
        return [RefundResponse.model_validate(refund) for refund in result.scalars()], len(all_refunds)

    async def approve_refund(self, db: AsyncSession, refund_id: int) -> RefundResponse:
        refund = await self._get_refund(db, refund_id)
        if refund.status != "pending_approval":
            raise AppException(40008, "当前售后状态不允许同意")
        refund.status = "approved"
        await db.commit()
        await db.refresh(refund)
        return RefundResponse.model_validate(refund)

    async def reject_refund(self, db: AsyncSession, refund_id: int) -> RefundResponse:
        refund = await self._get_refund(db, refund_id)
        if refund.status != "pending_approval":
            raise AppException(40008, "当前售后状态不允许拒绝")
        order = await self._get_order(db, refund.order_id)
        refund.status = "rejected"
        order.status = refund.origin_order_status
        await db.commit()
        await db.refresh(refund)
        return RefundResponse.model_validate(refund)

    async def receive_refund(self, db: AsyncSession, refund_id: int) -> RefundResponse:
        refund = await self._get_refund(db, refund_id)
        if refund.status != "approved":
            raise AppException(40008, "当前售后状态不允许确认收货")
        refund.status = "received"
        await db.commit()
        await db.refresh(refund)
        return RefundResponse.model_validate(refund)

    async def finish_refund(self, db: AsyncSession, refund_id: int) -> RefundResponse:
        refund = await self._get_refund(db, refund_id)
        if refund.status not in {"approved", "received"}:
            raise AppException(40008, "当前售后状态不允许退款")
        order = await self._get_order(db, refund.order_id)
        payment = await db.get(Payment, order.payment_id)
        should_restore_stock = refund.status == "received" and refund.refund_amount_cent >= order.pay_amount_cent
        refund.status = "refunded"
        order.status = "closed"
        if payment is not None:
            payment.status = "refunded" if refund.refund_amount_cent >= payment.pay_amount_cent else "partial_refunded"
        if should_restore_stock:
            await self._restore_refund_stock(db, order)
        await db.commit()
        await db.refresh(refund)
        return RefundResponse.model_validate(refund)

    async def get_payment(self, db: AsyncSession, user: User, payment_id: int) -> PaymentResponse:
        payment = await db.get(Payment, payment_id)
        if payment is None:
            raise AppException(40004, "支付单不存在", 404)
        if payment.user_id != user.id:
            raise ForbiddenException()
        return PaymentResponse.model_validate(payment)

    async def pay_payment(self, db: AsyncSession, user: User, payment_id: int) -> PaymentResponse:
        result = await db.execute(
            select(Payment).where(Payment.id == payment_id).options(selectinload(Payment.orders))
        )
        payment = result.scalars().unique().one_or_none()
        if payment is None:
            raise AppException(40004, "支付单不存在", 404)
        if payment.user_id != user.id:
            raise ForbiddenException()
        if payment.status != "unpaid":
            raise AppException(40008, "当前支付单状态不允许支付")
        payment.status = "paid"
        payment.paid_at = datetime.now(UTC)
        for order in payment.orders:
            if order.status == "pending_payment":
                order.status = "pending_shipment"
        await db.commit()
        return PaymentResponse.model_validate(payment)

    async def cancel_expired_unpaid_orders(
        self,
        db: AsyncSession,
        *,
        now: datetime | None = None,
        expire_minutes: int | None = None,
    ) -> int:
        now = now or datetime.now(UTC)
        expire_minutes = expire_minutes or settings.order_payment_expire_minutes
        expire_before = now - timedelta(minutes=expire_minutes)
        result = await db.execute(
            select(Order)
            .join(Payment, Order.payment_id == Payment.id)
            .where(
                Order.status == "pending_payment",
                Payment.status == "unpaid",
                Payment.created_at <= expire_before,
            )
            .options(selectinload(Order.items), selectinload(Order.payment))
        )
        orders = list(result.scalars().unique())
        for order in orders:
            await self._cancel_pending_order(db, order)
            if order.payment is not None:
                order.payment.status = "closed"
        await db.commit()
        return len(orders)

    async def auto_confirm_received_orders(
        self,
        db: AsyncSession,
        *,
        now: datetime | None = None,
        auto_confirm_days: int | None = None,
    ) -> int:
        now = now or datetime.now(UTC)
        auto_confirm_days = auto_confirm_days or settings.order_auto_confirm_days
        shipped_before = now - timedelta(days=auto_confirm_days)
        result = await db.execute(
            select(Order)
            .where(
                Order.status == "shipping",
                Order.shipped_at.is_not(None),
                Order.shipped_at <= shipped_before,
            )
            .options(selectinload(Order.items))
        )
        orders = list(result.scalars().unique())
        for order in orders:
            order.status = "completed"
            order.received_at = now
            await self._reward_grass_conversion(db, order)
        await db.commit()
        return len(orders)

    async def _validate_source_post(
        self,
        db: AsyncSession,
        user: User,
        source_post_id: int,
        order_product_ids: set[int],
    ) -> tuple[CommunityPost, set[int]]:
        post = await db.get(CommunityPost, source_post_id)
        if post is None or post.status != "published" or post.type != "grass":
            raise AppException(40005, "种草来源帖不可用")
        if post.user_id == user.id:
            raise AppException(40005, "不能使用自己的种草帖作为来源")
        post_product_ids = set(json.loads(post.product_ids or "[]"))
        matched_product_ids = post_product_ids & order_product_ids
        if not matched_product_ids:
            raise AppException(40005, "种草来源帖未关联本次购买商品")
        return post, matched_product_ids

    async def _cancel_pending_order(self, db: AsyncSession, order: Order) -> None:
        if order.status != "pending_payment":
            return
        order.status = "cancelled"
        for item in order.items:
            sku = await db.get(Sku, item.sku_id)
            if sku:
                await inventory_service.change_stock(
                    db,
                    sku,
                    change_quantity=item.quantity,
                    change_type="order_cancel_restore",
                    remark=f"取消订单回补库存：{order.order_no}",
                )

    async def _restore_refund_stock(self, db: AsyncSession, order: Order) -> None:
        for item in order.items:
            sku = await db.get(Sku, item.sku_id)
            if sku:
                await inventory_service.change_stock(
                    db,
                    sku,
                    change_quantity=item.quantity,
                    change_type="refund_restore",
                    remark=f"售后退货退款回补库存：{order.order_no}",
                )

    async def _reward_grass_conversion(self, db: AsyncSession, order: Order) -> None:
        if order.grass_rewarded or order.source_post_id is None or order.source_user_id is None:
            return
        if order.source_user_id == order.user_id:
            order.grass_rewarded = True
            return
        existing_result = await db.execute(
            select(GrassConversionReward).where(GrassConversionReward.order_id == order.id)
        )
        if existing_result.scalar_one_or_none() is not None:
            order.grass_rewarded = True
            return
        source_user = await db.get(User, order.source_user_id)
        if source_user is None:
            order.grass_rewarded = True
            return
        await points_service.change_points(
            db,
            source_user,
            change_points=self.GRASS_REWARD_POINTS,
            source_type="grass_conversion",
            source_id=order.id,
            description="种草订单确认收货奖励",
        )
        order.grass_rewarded = True
        db.add(
            GrassConversionReward(
                order_id=order.id,
                post_id=order.source_post_id,
                source_user_id=order.source_user_id,
                buyer_user_id=order.user_id,
                points=self.GRASS_REWARD_POINTS,
            )
        )

    async def _resolve_checkout_items(
        self,
        db: AsyncSession,
        user: User,
        request_items: list[CheckoutItemRequest] | None,
    ) -> list[CheckoutItemRequest]:
        if request_items is not None:
            return request_items
        result = await db.execute(select(CartItem).where(CartItem.user_id == user.id, CartItem.checked.is_(True)))
        return [CheckoutItemRequest(sku_id=item.sku_id, quantity=item.quantity) for item in result.scalars()]

    async def _cart_item_to_response(self, db: AsyncSession, item: CartItem) -> CartItemResponse:
        return await self._sku_quantity_to_cart_response(db, item.sku_id, item.quantity, item.checked)

    async def _sku_quantity_to_cart_response(
        self,
        db: AsyncSession,
        sku_id: int,
        quantity: int,
        checked: bool = True,
    ) -> CartItemResponse:
        sku = await self._get_sku(db, sku_id)
        invalid_reason = None
        if sku.product.status != "on_sale":
            invalid_reason = "商品未上架"
        elif sku.stock < quantity:
            invalid_reason = "库存不足"
        return CartItemResponse(
            sku_id=sku.id,
            product_id=sku.product_id,
            product_name=sku.product.name,
            sku_name=sku.name,
            price_cent=sku.price_cent,
            quantity=quantity,
            checked=checked,
            invalid_reason=invalid_reason,
        )

    async def _get_sku(self, db: AsyncSession, sku_id: int) -> Sku:
        result = await db.execute(
            select(Sku).where(Sku.id == sku_id).options(selectinload(Sku.product).selectinload(Product.merchant))
        )
        sku = result.scalars().one_or_none()
        if sku is None:
            raise AppException(40004, "SKU 不存在", 404)
        return sku

    async def _get_cart_item(self, db: AsyncSession, user_id: int, sku_id: int) -> CartItem:
        result = await db.execute(select(CartItem).where(CartItem.user_id == user_id, CartItem.sku_id == sku_id))
        cart_item = result.scalar_one_or_none()
        if cart_item is None:
            raise AppException(40004, "购物车商品不存在", 404)
        return cart_item

    async def _get_order(self, db: AsyncSession, order_id: int) -> Order:
        result = await db.execute(select(Order).where(Order.id == order_id).options(selectinload(Order.items)))
        order = result.scalars().unique().one_or_none()
        if order is None:
            raise AppException(40004, "订单不存在", 404)
        return order

    async def _get_refund(self, db: AsyncSession, refund_id: int) -> Refund:
        refund = await db.get(Refund, refund_id)
        if refund is None:
            raise AppException(40004, "售后单不存在", 404)
        return refund

    def _review_to_response(self, review: ProductReview) -> ReviewResponse:
        return ReviewResponse(
            id=review.id,
            user_id=review.user_id,
            order_id=review.order_id,
            product_id=review.product_id,
            score=review.score,
            content=review.content,
            image_urls=json.loads(review.image_urls or "[]"),
            status=review.status,
        )

    def _address_to_snapshot(self, address: UserAddress) -> dict:
        return {
            "receiver_name": address.receiver_name,
            "receiver_mobile": address.receiver_mobile,
            "province": address.province,
            "city": address.city,
            "district": address.district,
            "detail_address": address.detail_address,
        }

    def to_order_response(self, order: Order) -> OrderResponse:
        shipping_address = None
        if order.shipping_address_snapshot:
            shipping_address = ShippingAddressSnapshot(**json.loads(order.shipping_address_snapshot))
        return OrderResponse(
            id=order.id,
            order_no=order.order_no,
            payment_id=order.payment_id,
            merchant_id=order.merchant_id,
            status=order.status,
            total_amount_cent=order.total_amount_cent,
            pay_amount_cent=order.pay_amount_cent,
            source_post_id=order.source_post_id,
            source_user_id=order.source_user_id,
            shipping_address=shipping_address,
            logistics_company=order.logistics_company,
            tracking_no=order.tracking_no,
            shipped_at=order.shipped_at.isoformat() if order.shipped_at else None,
            received_at=order.received_at.isoformat() if order.received_at else None,
            items=[OrderItemResponse.model_validate(item) for item in order.items],
        )


order_service = OrderService()
