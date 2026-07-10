      
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.exceptions import AppException, ForbiddenException
from app.models.community import CommunityPost, GrassConversionReward
from app.models.group_buy import GroupBuyGroup, GroupBuyParticipant
from app.models.order import CartItem, Order, OrderItem, Payment, ProductReview, Refund, RefundLog
from app.models.product import Product, Sku
from app.models.user import User, UserAddress
from app.schemas.order import (
    CartAddRequest,
    CartBatchDeleteRequest,
    CartBatchUpdateRequest,
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
    AlipayPrecreateResponse,
    RefundCreateRequest,
    RefundLogResponse,
    RefundResponse,
    ReviewCreateRequest,
    ReviewResponse,
    ShipOrderRequest,
    ShippingAddressSnapshot,
)
from app.services.address_service import address_service
from app.services.alipay_service import alipay_service
from app.services.inventory_service import inventory_service
from app.services.platform_setting_service import platform_setting_service
from app.services.points_service import points_service
from app.services.promotion_service import promotion_service


@dataclass
class OrderPriceCalculation:
    total_amount_cent: int
    full_discount_amount_cent: int
    coupon_discount_amount_cent: int
    points_discount_amount_cent: int
    points_used: int
    max_points_usable: int
    pay_amount_cent: int
    user_coupon: object | None
    full_discount_activity: object | None

    @property
    def discount_amount_cent(self) -> int:
        return self.full_discount_amount_cent + self.coupon_discount_amount_cent + self.points_discount_amount_cent


class OrderService:
    GRASS_REWARD_RATE = 0.01

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

        source_post = None
        if payload.source_post_id is not None:
            source_post, _ = await self._validate_source_post(db, user, payload.source_post_id, {sku.product_id})
        result = await db.execute(select(CartItem).where(CartItem.user_id == user.id, CartItem.sku_id == payload.sku_id))
        cart_item = result.scalar_one_or_none()
        if cart_item is None:
            db.add(
                CartItem(
                    user_id=user.id,
                    sku_id=payload.sku_id,
                    quantity=payload.quantity,
                    checked=True,
                    source_post_id=source_post.id if source_post is not None else None,
                )
            )
        else:
            cart_item.quantity += payload.quantity
            cart_item.checked = True
            cart_item.source_post_id = source_post.id if source_post is not None else None
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

    async def batch_update_cart_items(
        self,
        db: AsyncSession,
        user: User,
        payload: CartBatchUpdateRequest,
    ) -> list[CartItemResponse]:
        result = await db.execute(
            select(CartItem).where(
                CartItem.user_id == user.id,
                CartItem.sku_id.in_(set(payload.sku_ids)),
            )
        )
        for item in result.scalars():
            item.checked = payload.checked
        await db.commit()
        return await self.list_cart(db, user)

    async def batch_delete_cart_items(
        self,
        db: AsyncSession,
        user: User,
        payload: CartBatchDeleteRequest,
    ) -> list[CartItemResponse]:
        statement = delete(CartItem).where(CartItem.user_id == user.id)
        if payload.sku_ids is not None:
            statement = statement.where(CartItem.sku_id.in_(set(payload.sku_ids)))
        await db.execute(statement)
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
        price = await self._calculate_order_price(
            db,
            user,
            sku_quantities,
            payload.full_discount_id,
            payload.coupon_id,
            payload.points_used,
        )
        full_discount_options = await promotion_service.list_full_discount_options(
            db,
            sku_quantities,
            selected_id=price.full_discount_activity.id if price.full_discount_activity is not None else None,
        )
        amount_after_full_discount = max(0, price.total_amount_cent - price.full_discount_amount_cent)
        coupon_options = await promotion_service.list_coupon_options(
            db,
            user,
            amount_after_full_discount,
            sku_quantities,
            selected_id=price.user_coupon.id if price.user_coupon is not None else None,
        )
        addresses = await address_service.list_addresses(db, user)
        return CheckoutResponse(
            items=cart_items,
            addresses=addresses,
            available_full_discounts=full_discount_options,
            available_coupons=coupon_options,
            selected_full_discount_id=price.full_discount_activity.id if price.full_discount_activity is not None else None,
            selected_coupon_id=price.user_coupon.id if price.user_coupon is not None else None,
            total_amount_cent=price.total_amount_cent,
            discount_amount_cent=price.discount_amount_cent,
            full_discount_amount_cent=price.full_discount_amount_cent,
            coupon_discount_amount_cent=price.coupon_discount_amount_cent,
            points_discount_amount_cent=price.points_discount_amount_cent,
            points_used=price.points_used,
            max_points_usable=price.max_points_usable,
            pay_amount_cent=price.pay_amount_cent,
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
        source_post_id = payload.source_post_id
        if source_post_id is None and payload.items is None:
            source_post_id = await self._source_post_id_from_checked_cart(db, user)
        source_post = None
        source_product_ids: set[int] = set()
        if source_post_id is not None:
            source_post, source_product_ids = await self._validate_source_post(
                db,
                user,
                source_post_id,
                {sku.product_id for sku, _ in sku_quantities},
            )

        price = await self._calculate_order_price(
            db,
            user,
            sku_quantities,
            payload.full_discount_id,
            payload.coupon_id,
            payload.points_used,
        )
        payment = Payment(
            payment_no=f"PAY{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}{uuid4().hex[:8]}",
            user_id=user.id,
            pay_amount_cent=price.pay_amount_cent,
            points_used=price.points_used,
            points_discount_amount_cent=price.points_discount_amount_cent,
        )
        db.add(payment)
        await db.flush()

        orders_by_merchant: dict[int, list[tuple[Sku, int]]] = {}
        for sku, quantity in sku_quantities:
            orders_by_merchant.setdefault(sku.product.merchant_id, []).append((sku, quantity))

        orders: list[Order] = []
        full_discount_by_merchant = promotion_service.allocate_full_discount_by_merchant(
            price.full_discount_amount_cent,
            price.full_discount_activity,
            sku_quantities,
        )
        coupon_discount_by_merchant = promotion_service.allocate_discount_by_merchant(
            price.coupon_discount_amount_cent,
            price.user_coupon,
            sku_quantities,
        )
        points_discount_by_merchant = self._allocate_points_discount_by_merchant(
            price.points_discount_amount_cent,
            sku_quantities,
        )
        for merchant_id, merchant_items in orders_by_merchant.items():
            order_amount = sum(sku.price_cent * quantity for sku, quantity in merchant_items)
            full_discount = min(order_amount, full_discount_by_merchant.get(merchant_id, 0))
            coupon_discount = min(order_amount - full_discount, coupon_discount_by_merchant.get(merchant_id, 0))
            points_discount = min(
                order_amount - full_discount - coupon_discount,
                points_discount_by_merchant.get(merchant_id, 0),
            )
            order_discount = full_discount + coupon_discount + points_discount
            order = Order(
                order_no=f"ORD{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}{uuid4().hex[:8]}",
                payment_id=payment.id,
                user_id=user.id,
                merchant_id=merchant_id,
                status="pending_payment",
                total_amount_cent=order_amount,
                pay_amount_cent=order_amount - order_discount,
                full_discount_amount_cent=full_discount,
                coupon_discount_amount_cent=coupon_discount,
                points_discount_amount_cent=points_discount,
                points_used=self._allocate_points_used_for_order(
                    price.points_used,
                    price.points_discount_amount_cent,
                    points_discount,
                ),
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
        await promotion_service.mark_coupon_used(db, price.user_coupon, orders[0].id if orders else None)
        if price.points_used > 0:
            await points_service.change_points(
                db,
                user,
                change_points=-price.points_used,
                source_type="order_points_deduction",
                source_id=payment.id,
                description=f"订单支付抵扣 {price.points_discount_amount_cent / 100:.2f} 元",
            )
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

    async def create_group_buy_order(
        self,
        db: AsyncSession,
        user: User,
        *,
        sku: Sku,
        quantity: int,
        unit_price_cent: int,
        client_order_token: str,
        shipping_address_id: int | None,
        points_used: int,
        group_id: int,
        activity_id: int,
    ) -> CreateOrderResponse:
        existing_result = await db.execute(
            select(Order)
            .where(Order.user_id == user.id, Order.client_order_token == client_order_token)
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
        if sku.product.status != "on_sale":
            raise AppException(40005, "商品未上架")
        if sku.stock < quantity:
            raise AppException(40007, "库存不足")
        address_snapshot = None
        if shipping_address_id is not None:
            address = await address_service.get_owned_address(db, user, shipping_address_id)
            address_snapshot = self._address_to_snapshot(address)
        total_amount = unit_price_cent * quantity
        points_used, points_discount, _ = await self._calculate_points_discount(db, user, points_used, total_amount)
        payment = Payment(
            payment_no=f"PAY{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}{uuid4().hex[:8]}",
            user_id=user.id,
            pay_amount_cent=max(0, total_amount - points_discount),
            points_used=points_used,
            points_discount_amount_cent=points_discount,
        )
        db.add(payment)
        await db.flush()
        order = Order(
            order_no=f"ORD{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}{uuid4().hex[:8]}",
            payment_id=payment.id,
            user_id=user.id,
            merchant_id=sku.product.merchant_id,
            status="pending_payment",
            total_amount_cent=total_amount,
            pay_amount_cent=max(0, total_amount - points_discount),
            points_discount_amount_cent=points_discount,
            points_used=points_used,
            client_order_token=client_order_token,
            order_type="group_buy",
            group_buy_activity_id=activity_id,
            group_buy_group_id=group_id,
            shipping_address_snapshot=json.dumps(address_snapshot, ensure_ascii=False) if address_snapshot else None,
        )
        order.items = [
            OrderItem(
                product_id=sku.product_id,
                sku_id=sku.id,
                product_name=sku.product.name,
                sku_name=sku.name,
                unit_price_cent=unit_price_cent,
                quantity=quantity,
                total_amount_cent=total_amount,
            )
        ]
        db.add(order)
        await inventory_service.change_stock(
            db,
            sku,
            change_quantity=-quantity,
            change_type="group_buy_lock",
            remark=f"创建拼团订单扣减库存：{order.order_no}",
        )
        if points_used > 0:
            await points_service.change_points(
                db,
                user,
                change_points=-points_used,
                source_type="group_buy_points_deduction",
                source_id=payment.id,
                description=f"拼团支付抵扣 {points_discount / 100:.2f} 元",
            )
        await db.flush()
        return CreateOrderResponse(
            payment_id=payment.id,
            payment_no=payment.payment_no,
            order_ids=[order.id],
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
            .options(
                selectinload(Order.merchant),
                selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.images),
            )
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
        payment_result = await db.execute(
            select(Payment)
            .where(Payment.id == order.payment_id)
            .options(selectinload(Payment.orders).selectinload(Order.items))
        )
        payment = payment_result.scalars().unique().one_or_none()
        if payment is None:
            raise AppException(40004, "支付单不存在", 404)
        if payment.status != "unpaid":
            raise AppException(40008, "当前支付单状态不允许取消")
        for payment_order in payment.orders:
            if payment_order.user_id != user.id:
                raise ForbiddenException()
            if payment_order.status == "pending_payment":
                await self._cancel_pending_order(db, payment_order)
        payment.status = "closed"
        await self._restore_payment_points_if_needed(db, payment)
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
        score: int | None = None,
        has_image: bool | None = None,
    ) -> tuple[list[ReviewResponse], int]:
        if score is not None and (score < 1 or score > 5):
            raise AppException(40001, "评分筛选必须在 1-5 之间")
        statement = select(ProductReview).where(ProductReview.product_id == product_id)
        if not include_pending:
            statement = statement.where(ProductReview.status == "published")
        if score is not None:
            statement = statement.where(ProductReview.score == score)
        if has_image is True:
            statement = statement.where(ProductReview.image_urls != "[]")
        statement = statement.order_by(ProductReview.created_at.desc())
        all_result = await db.execute(statement)
        all_reviews = list(all_result.scalars())
        result = await db.execute(statement.offset((page - 1) * page_size).limit(page_size))
        reviews = list(result.scalars())
        users_by_id = await self._review_users_by_id(db, [review.user_id for review in reviews])
        return [self._review_to_response(review, users_by_id.get(review.user_id)) for review in reviews], len(all_reviews)

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
        active_order_refund_result = await db.execute(
            select(Refund).where(Refund.order_id == order_id, Refund.status.in_(["pending_approval", "approved", "received"]))
        )
        if active_order_refund_result.scalar_one_or_none() is not None:
            raise AppException(40005, "该订单已有处理中售后")
        order_item = next((item for item in order.items if item.id == payload.order_item_id), None)
        if order_item is None:
            raise AppException(40005, "只能申请本订单内商品售后")
        existing_result = await db.execute(
            select(Refund).where(
                Refund.order_item_id == order_item.id,
                Refund.status.in_(["pending_approval", "approved", "received"]),
            )
        )
        if existing_result.scalar_one_or_none() is not None:
            raise AppException(40005, "该订单商品已申请售后")
        refunded_quantity = await self._refunded_item_quantity(db, order_item.id)
        if refunded_quantity + payload.quantity > order_item.quantity:
            raise AppException(40005, "退款数量不能超过该商品剩余可退数量")
        refunded_amount = await self._refunded_item_amount(db, order_item.id)
        refund_amount = self._calculate_item_refund_amount(
            order,
            order_item,
            payload.quantity,
            refunded_quantity=refunded_quantity,
            refunded_amount=refunded_amount,
        )
        refund = Refund(
            order_id=order_id,
            order_item_id=order_item.id,
            product_id=order_item.product_id,
            sku_id=order_item.sku_id,
            user_id=user.id,
            quantity=payload.quantity,
            refund_amount_cent=refund_amount,
            reason_type=payload.reason_type,
            reason=payload.reason,
            image_urls=json.dumps(payload.image_urls, ensure_ascii=False),
            status="pending_approval",
            origin_order_status=order.status,
        )
        order.status = "after_sale"
        db.add(refund)
        await db.flush()
        self._add_refund_log(db, refund, "user", user.id, "create", f"用户申请售后，数量 {payload.quantity}")
        await db.commit()
        await db.refresh(refund)
        return await self._refund_to_response(db, refund)

    async def list_refunds(
        self,
        db: AsyncSession,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        merchant_id: int | None = None,
        order_id: int | None = None,
        user_id: int | None = None,
    ) -> tuple[list[RefundResponse], int]:
        statement = select(Refund)
        if merchant_id is not None:
            statement = statement.join(Order, Refund.order_id == Order.id).where(Order.merchant_id == merchant_id)
        if status:
            statement = statement.where(Refund.status == status)
        if order_id is not None:
            statement = statement.where(Refund.order_id == order_id)
        if user_id is not None:
            statement = statement.where(Refund.user_id == user_id)
        statement = statement.order_by(Refund.created_at.desc())
        all_result = await db.execute(statement)
        all_refunds = list(all_result.scalars())
        result = await db.execute(statement.offset((page - 1) * page_size).limit(page_size))
        refunds = list(result.scalars())
        return [await self._refund_to_response(db, refund) for refund in refunds], len(all_refunds)

    async def list_user_refunds(
        self,
        db: AsyncSession,
        user: User,
        *,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[RefundResponse], int]:
        statement = select(Refund).where(Refund.user_id == user.id)
        if status:
            statement = statement.where(Refund.status == status)
        statement = statement.order_by(Refund.updated_at.desc(), Refund.id.desc())
        all_result = await db.execute(statement)
        all_refunds = list(all_result.scalars())
        result = await db.execute(statement.offset((page - 1) * page_size).limit(page_size))
        refunds = list(result.scalars())
        return [await self._refund_to_response(db, refund) for refund in refunds], len(all_refunds)

    async def get_user_refund(self, db: AsyncSession, user: User, refund_id: int) -> RefundResponse:
        refund = await self._get_refund(db, refund_id)
        if refund.user_id != user.id:
            raise ForbiddenException()
        return await self._refund_to_response(db, refund)

    async def approve_refund(self, db: AsyncSession, refund_id: int) -> RefundResponse:
        refund = await self._get_refund(db, refund_id)
        if refund.status != "pending_approval":
            raise AppException(40008, "当前售后状态不允许同意")
        refund.status = "approved"
        self._add_refund_log(db, refund, "admin", None, "approve", "平台同意售后")
        await db.commit()
        await db.refresh(refund)
        return await self._refund_to_response(db, refund)

    async def reject_refund(self, db: AsyncSession, refund_id: int) -> RefundResponse:
        refund = await self._get_refund(db, refund_id)
        if refund.status != "pending_approval":
            raise AppException(40008, "当前售后状态不允许拒绝")
        order = await self._get_order(db, refund.order_id)
        refund.status = "rejected"
        order.status = refund.origin_order_status
        self._add_refund_log(db, refund, "admin", None, "reject", "平台拒绝售后")
        await db.commit()
        await db.refresh(refund)
        return await self._refund_to_response(db, refund)

    async def receive_refund(self, db: AsyncSession, refund_id: int) -> RefundResponse:
        refund = await self._get_refund(db, refund_id)
        if refund.status != "approved":
            raise AppException(40008, "当前售后状态不允许确认收货")
        refund.status = "received"
        self._add_refund_log(db, refund, "admin", None, "receive", "平台确认收到退货")
        await db.commit()
        await db.refresh(refund)
        return await self._refund_to_response(db, refund)

    async def finish_refund(self, db: AsyncSession, refund_id: int) -> RefundResponse:
        refund = await self._get_refund(db, refund_id)
        if refund.status not in {"approved", "received"}:
            raise AppException(40008, "当前售后状态不允许退款")
        order = await self._get_order(db, refund.order_id)
        payment = await db.get(Payment, order.payment_id)
        should_restore_stock = refund.status == "received" and refund.order_item_id is not None
        refund.status = "refunded"
        if await self._is_order_fully_refunded(db, order):
            order.status = "closed"
        else:
            order.status = refund.origin_order_status
        if payment is not None:
            refunded_amount = await self._payment_refunded_amount(db, payment.id)
            payment.status = "refunded" if refunded_amount >= payment.pay_amount_cent else "partial_refunded"
        if should_restore_stock:
            await self._restore_refund_stock(db, order, refund)
        self._add_refund_log(db, refund, "admin", None, "refund", "平台确认退款完成")
        await db.commit()
        await db.refresh(refund)
        return await self._refund_to_response(db, refund)

    async def get_payment(self, db: AsyncSession, user: User, payment_id: int) -> PaymentResponse:
        payment = await self._get_payment_with_orders(db, payment_id)
        if payment is None:
            raise AppException(40004, "支付单不存在", 404)
        if payment.user_id != user.id:
            raise ForbiddenException()
        return self._payment_to_response(payment)

    async def pay_payment(self, db: AsyncSession, user: User, payment_id: int) -> PaymentResponse:
        if not settings.payment_mock_enabled:
            raise AppException(40005, "模拟支付未开启，请在后端 .env 设置 PAYMENT_MOCK_ENABLED=true 后重启服务")
        payment = await self._get_payment_with_orders(db, payment_id)
        if payment is None:
            raise AppException(40004, "支付单不存在", 404)
        if payment.user_id != user.id:
            raise ForbiddenException()
        if payment.status != "unpaid":
            raise AppException(40008, "当前支付单状态不允许支付")
        await self._mark_payment_paid(db, payment, channel="mock")
        await db.commit()
        return self._payment_to_response(payment)

    async def precreate_alipay_payment(
        self,
        db: AsyncSession,
        user: User,
        payment_id: int,
        force: bool = False,
    ) -> AlipayPrecreateResponse:
        payment = await self._get_payment_with_orders(db, payment_id)
        if payment is None:
            raise AppException(40004, "支付单不存在", 404)
        if payment.user_id != user.id:
            raise ForbiddenException()
        if payment.status != "unpaid":
            raise AppException(40008, "当前支付单状态不允许发起支付宝支付")
        if payment.alipay_qr_code and not force:
            qr_code = payment.alipay_qr_code
        else:
            if force:
                payment.alipay_qr_code = None
                payment.alipay_trade_no = None
                payment.alipay_buyer_logon_id = None
                await db.flush()
            qr_code = await alipay_service.precreate(db, payment)
            payment = await self._get_payment_with_orders(db, payment_id)
            if payment is None:
                raise AppException(40004, "支付单不存在", 404)
        return AlipayPrecreateResponse(
            payment=self._payment_to_response(payment),
            qr_code=qr_code,
            payment_no=payment.payment_no,
            expire_minutes=120,
        )

    async def sync_alipay_payment(self, db: AsyncSession, user: User, payment_id: int) -> PaymentResponse:
        payment = await self._get_payment_with_orders(db, payment_id)
        if payment is None:
            raise AppException(40004, "支付单不存在", 404)
        if payment.user_id != user.id:
            raise ForbiddenException()
        if settings.payment_mock_enabled:
            if payment.status == "unpaid":
                await self._mark_payment_paid(db, payment, channel="mock")
                await db.flush()
                await db.commit()
                payment = await self._get_payment_with_orders(db, payment_id)
                if payment is None:
                    raise AppException(40004, "支付单不存在", 404)
            return self._payment_to_response(payment)
        result = await alipay_service.query(payment)
        if result.get("trade_status") in alipay_service.SUCCESS_TRADE_STATUS:
            await self._mark_payment_paid(
                db,
                payment,
                channel="alipay",
                alipay_trade_no=result.get("trade_no"),
                buyer_logon_id=result.get("buyer_logon_id"),
            )
            await db.commit()
            payment = await self._get_payment_with_orders(db, payment_id)
            if payment is None:
                raise AppException(40004, "支付单不存在", 404)
        return self._payment_to_response(payment)

    async def handle_alipay_notify(self, db: AsyncSession, payload: dict[str, str]) -> bool:
        if not alipay_service.verify_notify(payload):
            return False
        payment_no = payload.get("out_trade_no")
        if not payment_no:
            return False
        result = await db.execute(
            select(Payment)
            .where(Payment.payment_no == payment_no)
            .options(selectinload(Payment.orders).selectinload(Order.items))
        )
        payment = result.scalars().unique().one_or_none()
        if payment is None:
            return False
        payment.alipay_notify_at = datetime.now(UTC)
        if payload.get("trade_status") in alipay_service.SUCCESS_TRADE_STATUS:
            await self._mark_payment_paid(
                db,
                payment,
                channel="alipay",
                alipay_trade_no=payload.get("trade_no"),
                buyer_logon_id=payload.get("buyer_logon_id"),
            )
        await db.commit()
        return True

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
        restored_payment_ids: set[int] = set()
        for order in orders:
            await self._cancel_pending_order(db, order)
            if order.payment is not None:
                order.payment.status = "closed"
                if order.payment.id not in restored_payment_ids:
                    await self._restore_payment_points_if_needed(db, order.payment)
                    restored_payment_ids.add(order.payment.id)
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

    async def _calculate_order_price(
        self,
        db: AsyncSession,
        user: User,
        sku_quantities: list[tuple[Sku, int]],
        full_discount_id: int | None,
        coupon_id: int | None,
        requested_points: int,
    ) -> OrderPriceCalculation:
        total_amount = sum(sku.price_cent * quantity for sku, quantity in sku_quantities)
        full_discount_amount, full_discount_activity = await promotion_service.calculate_full_discount(
            db,
            sku_quantities,
            full_discount_id,
        )
        amount_after_full_discount = max(0, total_amount - full_discount_amount)
        coupon_discount_amount, user_coupon = await promotion_service.calculate_coupon_discount(
            db,
            user,
            coupon_id,
            amount_after_full_discount,
            sku_quantities,
        )
        amount_before_points = max(0, amount_after_full_discount - coupon_discount_amount)
        points_used, points_discount_amount, max_points_usable = await self._calculate_points_discount(
            db,
            user,
            requested_points,
            amount_before_points,
        )
        return OrderPriceCalculation(
            total_amount_cent=total_amount,
            full_discount_amount_cent=full_discount_amount,
            coupon_discount_amount_cent=coupon_discount_amount,
            points_discount_amount_cent=points_discount_amount,
            points_used=points_used,
            max_points_usable=max_points_usable,
            pay_amount_cent=max(0, amount_before_points - points_discount_amount),
            user_coupon=user_coupon,
            full_discount_activity=full_discount_activity,
        )

    async def _calculate_points_discount(
        self,
        db: AsyncSession,
        user: User,
        requested_points: int,
        amount_before_points: int,
    ) -> tuple[int, int, int]:
        config = await platform_setting_service.get_member_points_config(db)
        level_rule = await self._resolve_member_level_rule(db, user, config)
        discount_percent = level_rule.max_points_discount_percent
        if discount_percent is None:
            discount_percent = config.max_points_discount_percent
        max_discount_amount = amount_before_points * discount_percent // 100
        max_points_by_amount = max_discount_amount * config.points_to_yuan_rate // 100
        max_points_usable = max(0, min(user.points, max_points_by_amount))
        if requested_points <= 0 or amount_before_points <= 0 or max_points_usable <= 0:
            return 0, 0, max_points_usable
        if requested_points > max_points_usable:
            raise AppException(40005, f"本次最多可使用 {max_points_usable} 积分")
        discount_amount = requested_points * 100 // config.points_to_yuan_rate
        discount_amount = min(discount_amount, max_discount_amount, amount_before_points)
        if discount_amount <= 0:
            raise AppException(40005, "使用积分不足以抵扣 0.01 元")
        return requested_points, discount_amount, max_points_usable

    async def _resolve_member_level_rule(self, db: AsyncSession, user: User, config):
        growth_value = await db.scalar(
            select(func.coalesce(func.sum(Order.pay_amount_cent), 0)).where(
                Order.user_id == user.id,
                Order.status.in_(["completed", "closed", "after_sale"]),
            )
        ) or 0
        rules = sorted(config.level_rules, key=lambda item: item.threshold_cent, reverse=True)
        for rule in rules:
            if int(growth_value) >= rule.threshold_cent:
                user.level = rule.level
                return rule
        return min(config.level_rules, key=lambda item: item.threshold_cent)

    def _allocate_points_discount_by_merchant(
        self,
        points_discount_amount: int,
        sku_quantities: list[tuple[Sku, int]],
    ) -> dict[int, int]:
        return promotion_service.allocate_discount_by_merchant(points_discount_amount, None, sku_quantities)

    def _allocate_points_used_for_order(
        self,
        total_points_used: int,
        total_points_discount_amount: int,
        order_points_discount_amount: int,
    ) -> int:
        if total_points_used <= 0 or total_points_discount_amount <= 0 or order_points_discount_amount <= 0:
            return 0
        return min(
            total_points_used,
            round(total_points_used * order_points_discount_amount / total_points_discount_amount),
        )

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

    async def _restore_payment_points_if_needed(self, db: AsyncSession, payment: Payment) -> None:
        if payment.points_used <= 0:
            return
        user = await db.get(User, payment.user_id)
        if user is None:
            return
        await points_service.change_points(
            db,
            user,
            change_points=payment.points_used,
            source_type="order_points_restore",
            source_id=payment.id,
            description=f"支付单关闭退回积分：{payment.payment_no}",
        )

    async def _restore_refund_stock(self, db: AsyncSession, order: Order, refund: Refund) -> None:
        if refund.sku_id is None or refund.quantity <= 0:
            return
        sku = await db.get(Sku, refund.sku_id)
        if sku:
            await inventory_service.change_stock(
                db,
                sku,
                change_quantity=refund.quantity,
                change_type="refund_restore",
                remark=f"售后退货退款回补库存：{order.order_no} / 明细 {refund.order_item_id}",
            )

    def _add_refund_log(
        self,
        db: AsyncSession,
        refund: Refund,
        operator_type: str,
        operator_id: int | None,
        action: str,
        message: str,
    ) -> None:
        refund_log = RefundLog(
            refund_id=refund.id,
            operator_type=operator_type,
            operator_id=operator_id,
            action=action,
            message=message,
        )
        db.add(refund_log)

    async def _refund_to_response(self, db: AsyncSession, refund: Refund) -> RefundResponse:
        result = await db.execute(
            select(RefundLog)
            .where(RefundLog.refund_id == refund.id)
            .order_by(RefundLog.created_at.asc(), RefundLog.id.asc())
        )
        logs = [
            RefundLogResponse(
                id=log.id,
                operator_type=log.operator_type,
                operator_id=log.operator_id,
                action=log.action,
                message=log.message,
                created_at=log.created_at.isoformat() if log.created_at else None,
            )
            for log in result.scalars()
        ]
        return RefundResponse(
            id=refund.id,
            order_id=refund.order_id,
            order_item_id=refund.order_item_id,
            product_id=refund.product_id,
            sku_id=refund.sku_id,
            user_id=refund.user_id,
            quantity=refund.quantity,
            refund_amount_cent=refund.refund_amount_cent,
            reason_type=refund.reason_type,
            reason=refund.reason,
            image_urls=json.loads(refund.image_urls or "[]"),
            status=refund.status,
            origin_order_status=refund.origin_order_status,
            created_at=refund.created_at.isoformat() if refund.created_at else None,
            updated_at=refund.updated_at.isoformat() if refund.updated_at else None,
            logs=logs,
        )

    def _calculate_item_refund_amount(
        self,
        order: Order,
        order_item: OrderItem,
        refund_quantity: int,
        *,
        refunded_quantity: int = 0,
        refunded_amount: int = 0,
    ) -> int:
        if order.total_amount_cent <= 0:
            return min(order_item.unit_price_cent * refund_quantity, order.pay_amount_cent)
        item_paid_amount = round(order.pay_amount_cent * order_item.total_amount_cent / order.total_amount_cent)
        if order_item.total_amount_cent > 0 and order.pay_amount_cent > 0:
            item_paid_amount = max(1, item_paid_amount)
        if refunded_quantity + refund_quantity >= order_item.quantity:
            return max(0, min(item_paid_amount - refunded_amount, order.pay_amount_cent))
        amount = round(item_paid_amount * refund_quantity / order_item.quantity)
        if refund_quantity > 0 and item_paid_amount > 0:
            amount = max(1, amount)
        return min(amount, order.pay_amount_cent)

    async def _refunded_item_quantity(self, db: AsyncSession, order_item_id: int) -> int:
        result = await db.execute(
            select(Refund).where(
                Refund.order_item_id == order_item_id,
                Refund.status == "refunded",
            )
        )
        return sum(refund.quantity for refund in result.scalars())

    async def _refunded_item_amount(self, db: AsyncSession, order_item_id: int) -> int:
        result = await db.execute(
            select(Refund).where(
                Refund.order_item_id == order_item_id,
                Refund.status == "refunded",
            )
        )
        return sum(refund.refund_amount_cent for refund in result.scalars())

    async def _payment_refunded_amount(self, db: AsyncSession, payment_id: int) -> int:
        result = await db.execute(
            select(Refund)
            .join(Order, Refund.order_id == Order.id)
            .where(Order.payment_id == payment_id, Refund.status == "refunded")
        )
        return sum(refund.refund_amount_cent for refund in result.scalars())

    async def _is_order_fully_refunded(self, db: AsyncSession, order: Order) -> bool:
        if not order.items:
            return False
        result = await db.execute(
            select(Refund).where(
                Refund.order_id == order.id,
                Refund.status == "refunded",
                Refund.order_item_id.is_not(None),
            )
        )
        refunded_item_ids = {refund.order_item_id for refund in result.scalars()}
        for item in order.items:
            if item.id not in refunded_item_ids:
                return False
            if await self._refunded_item_quantity(db, item.id) < item.quantity:
                return False
        return True

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
        post = await db.get(CommunityPost, order.source_post_id)
        if post is None:
            order.grass_rewarded = True
            return
        post_product_ids = set(json.loads(post.product_ids or "[]"))
        reward_base_amount = sum(
            item.unit_price_cent * item.quantity for item in order.items if item.product_id in post_product_ids
        )
        reward_points = int(reward_base_amount * self.GRASS_REWARD_RATE)
        if reward_points <= 0:
            order.grass_rewarded = True
            return
        await points_service.change_points(
            db,
            source_user,
            change_points=reward_points,
            source_type="grass_conversion",
            source_id=order.id,
            description="种草订单确认收货，推广人获得商品原价 1% 积分奖励",
        )
        buyer = await db.get(User, order.user_id)
        if buyer is not None:
            await points_service.change_points(
                db,
                buyer,
                change_points=reward_points,
                source_type="grass_conversion_buyer",
                source_id=order.id,
                description="通过种草帖下单确认收货，买家获得商品原价 1% 积分奖励",
            )
        order.grass_rewarded = True
        db.add(
            GrassConversionReward(
                order_id=order.id,
                post_id=order.source_post_id,
                source_user_id=order.source_user_id,
                buyer_user_id=order.user_id,
                points=reward_points,
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

    async def _source_post_id_from_checked_cart(self, db: AsyncSession, user: User) -> int | None:
        result = await db.execute(
            select(CartItem.source_post_id).where(
                CartItem.user_id == user.id,
                CartItem.checked.is_(True),
                CartItem.source_post_id.is_not(None),
            )
        )
        source_post_ids = {source_post_id for source_post_id in result.scalars() if source_post_id is not None}
        if len(source_post_ids) == 1:
            return next(iter(source_post_ids))
        return None

    async def _cart_item_to_response(self, db: AsyncSession, item: CartItem) -> CartItemResponse:
        return await self._sku_quantity_to_cart_response(
            db,
            item.sku_id,
            item.quantity,
            item.checked,
            source_post_id=item.source_post_id,
        )

    async def _sku_quantity_to_cart_response(
        self,
        db: AsyncSession,
        sku_id: int,
        quantity: int,
        checked: bool = True,
        source_post_id: int | None = None,
    ) -> CartItemResponse:
        sku = await self._get_sku(db, sku_id)
        invalid_reason = None
        if sku.product.status != "on_sale":
            invalid_reason = "商品未上架"
        elif sku.stock < quantity:
            invalid_reason = "库存不足"
        cover_url = sku.product.cover_url
        if not cover_url and sku.product.images:
            first_image = sorted(sku.product.images, key=lambda image: (image.sort_order, image.id))[0]
            cover_url = first_image.url
        return CartItemResponse(
            sku_id=sku.id,
            product_id=sku.product_id,
            merchant_id=sku.product.merchant_id,
            merchant_name=sku.product.merchant.name if sku.product.merchant else f"店铺 #{sku.product.merchant_id}",
            merchant_logo_url=sku.product.merchant.logo_url if sku.product.merchant else None,
            product_name=sku.product.name,
            sku_name=sku.name,
            price_cent=sku.price_cent,
            quantity=quantity,
            checked=checked,
            cover_url=cover_url,
            source_post_id=source_post_id,
            source_label="种草来源" if source_post_id is not None else None,
            invalid_reason=invalid_reason,
        )

    async def _get_sku(self, db: AsyncSession, sku_id: int) -> Sku:
        result = await db.execute(
            select(Sku).where(Sku.id == sku_id).options(
                selectinload(Sku.product).selectinload(Product.merchant),
                selectinload(Sku.product).selectinload(Product.images),
            )
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
        result = await db.execute(
            select(Order)
            .where(Order.id == order_id)
            .options(
                selectinload(Order.merchant),
                selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.images),
            )
        )
        order = result.scalars().unique().one_or_none()
        if order is None:
            raise AppException(40004, "订单不存在", 404)
        return order

    async def _get_refund(self, db: AsyncSession, refund_id: int) -> Refund:
        refund = await db.get(Refund, refund_id)
        if refund is None:
            raise AppException(40004, "售后单不存在", 404)
        return refund

    async def _get_payment_with_orders(self, db: AsyncSession, payment_id: int) -> Payment | None:
        result = await db.execute(
            select(Payment)
            .where(Payment.id == payment_id)
            .options(
                selectinload(Payment.orders).selectinload(Order.merchant),
                selectinload(Payment.orders)
                .selectinload(Order.items)
                .selectinload(OrderItem.product)
                .selectinload(Product.images)
            )
        )
        return result.scalars().unique().one_or_none()

    async def _mark_payment_paid(
        self,
        db: AsyncSession,
        payment: Payment,
        *,
        channel: str,
        alipay_trade_no: str | None = None,
        buyer_logon_id: str | None = None,
    ) -> None:
        if payment.status in {"paid", "partial_refunded", "refunded"}:
            if alipay_trade_no:
                payment.alipay_trade_no = alipay_trade_no
            if buyer_logon_id:
                payment.alipay_buyer_logon_id = buyer_logon_id
            return
        if payment.status != "unpaid":
            raise AppException(40008, "当前支付单状态不允许支付")
        payment.status = "paid"
        payment.channel = channel
        payment.paid_at = datetime.now(UTC)
        if alipay_trade_no:
            payment.alipay_trade_no = alipay_trade_no
        if buyer_logon_id:
            payment.alipay_buyer_logon_id = buyer_logon_id
        for order in payment.orders:
            if order.status == "pending_payment":
                order.status = "group_pending" if order.order_type == "group_buy" else "pending_shipment"
                if order.order_type != "group_buy":
                    for item in order.items:
                        product = await db.get(Product, item.product_id)
                        if product:
                            product.sales_count += item.quantity
        await self._sync_paid_group_buy_participants(db, payment)
        await db.flush()
        from app.services.group_buy_service import group_buy_service

        await group_buy_service.sync_groups_for_payment(db, payment)

    async def mark_group_success_orders(self, db: AsyncSession, group_id: int) -> None:
        result = await db.execute(
            select(Order)
            .where(
                Order.group_buy_group_id == group_id,
                Order.order_type == "group_buy",
                Order.status == "group_pending",
            )
            .options(selectinload(Order.items))
        )
        for order in result.scalars():
            order.status = "pending_shipment"
            for item in order.items:
                product = await db.get(Product, item.product_id)
                if product:
                    product.sales_count += item.quantity

    async def _sync_paid_group_buy_participants(self, db: AsyncSession, payment: Payment) -> None:
        order_ids = [order.id for order in payment.orders if order.order_type == "group_buy"]
        if not order_ids:
            return
        result = await db.execute(select(GroupBuyParticipant).where(GroupBuyParticipant.order_id.in_(order_ids)))
        for participant in result.scalars():
            participant.status = "paid"

    def _payment_to_response(self, payment: Payment) -> PaymentResponse:
        return PaymentResponse(
            id=payment.id,
            payment_no=payment.payment_no,
            status=payment.status,
            pay_amount_cent=payment.pay_amount_cent,
            points_used=payment.points_used,
            points_discount_amount_cent=payment.points_discount_amount_cent,
            channel=payment.channel,
            alipay_trade_no=payment.alipay_trade_no,
            alipay_qr_code=payment.alipay_qr_code,
            alipay_buyer_logon_id=payment.alipay_buyer_logon_id,
            order_ids=[order.id for order in payment.orders],
            paid_at=payment.paid_at.isoformat() if payment.paid_at else None,
        )

    async def _review_users_by_id(self, db: AsyncSession, user_ids: list[int]) -> dict[int, User]:
        if not user_ids:
            return {}
        result = await db.execute(select(User).where(User.id.in_(set(user_ids))))
        return {user.id: user for user in result.scalars()}

    def _review_to_response(self, review: ProductReview, user: User | None = None) -> ReviewResponse:
        return ReviewResponse(
            id=review.id,
            user_id=review.user_id,
            user_nickname=user.nickname if user is not None else None,
            user_avatar_url=user.avatar_url if user is not None else None,
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
            "street": address.street,
            "detail_address": address.detail_address,
            "postal_code": address.postal_code,
            "address_tag": address.address_tag,
        }

    def _order_item_cover_url(self, item: OrderItem) -> str | None:
        product = getattr(item, "product", None)
        if product is None:
            return None
        cover_url = product.cover_url
        if not cover_url and product.images:
            first_image = sorted(product.images, key=lambda image: (image.sort_order, image.id))[0]
            cover_url = first_image.url
        return cover_url

    def to_order_response(self, order: Order) -> OrderResponse:
        shipping_address = None
        if order.shipping_address_snapshot:
            shipping_address = ShippingAddressSnapshot(**json.loads(order.shipping_address_snapshot))
        return OrderResponse(
            id=order.id,
            order_no=order.order_no,
            payment_id=order.payment_id,
            merchant_id=order.merchant_id,
            merchant_name=order.merchant.name if getattr(order, "merchant", None) else f"店铺 #{order.merchant_id}",
            merchant_logo_url=order.merchant.logo_url if getattr(order, "merchant", None) else None,
            status=order.status,
            total_amount_cent=order.total_amount_cent,
            pay_amount_cent=order.pay_amount_cent,
            full_discount_amount_cent=order.full_discount_amount_cent,
            coupon_discount_amount_cent=order.coupon_discount_amount_cent,
            points_discount_amount_cent=order.points_discount_amount_cent,
            points_used=order.points_used,
            source_post_id=order.source_post_id,
            source_user_id=order.source_user_id,
            order_type=order.order_type,
            group_buy_activity_id=order.group_buy_activity_id,
            group_buy_group_id=order.group_buy_group_id,
            shipping_address=shipping_address,
            logistics_company=order.logistics_company,
            tracking_no=order.tracking_no,
            created_at=order.created_at.isoformat() if order.created_at else None,
            shipped_at=order.shipped_at.isoformat() if order.shipped_at else None,
            received_at=order.received_at.isoformat() if order.received_at else None,
            items=[
                OrderItemResponse(
                    id=item.id,
                    product_id=item.product_id,
                    sku_id=item.sku_id,
                    product_name=item.product_name,
                    sku_name=item.sku_name,
                    cover_url=self._order_item_cover_url(item),
                    unit_price_cent=item.unit_price_cent,
                    quantity=item.quantity,
                    total_amount_cent=item.total_amount_cent,
                )
                for item in order.items
            ],
        )


order_service = OrderService()

    
