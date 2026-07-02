from fastapi import APIRouter

from app.api.v1.admin.router import router as admin_router
from app.api.v1.auth.router import router as auth_router
from app.api.v1.cart.router import router as cart_router
from app.api.v1.categories.router import router as categories_router
from app.api.v1.community.router import router as community_router
from app.api.v1.merchants.router import router as merchants_router
from app.api.v1.orders.router import router as orders_router
from app.api.v1.payments.router import router as payments_router
from app.api.v1.products.router import router as products_router
from app.api.v1.promotions.router import router as promotions_router
from app.api.v1.upload.router import router as upload_router
from app.api.v1.users.router import router as users_router
from app.api.v1.ws.router import router as ws_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(products_router, prefix="/products", tags=["products"])
api_router.include_router(categories_router, prefix="/categories", tags=["categories"])
api_router.include_router(merchants_router, prefix="/merchants", tags=["merchants"])
api_router.include_router(cart_router, prefix="/cart", tags=["cart"])
api_router.include_router(orders_router, prefix="/orders", tags=["orders"])
api_router.include_router(payments_router, prefix="/payments", tags=["payments"])
api_router.include_router(promotions_router, prefix="/promotions", tags=["promotions"])
api_router.include_router(community_router, prefix="/community", tags=["community"])
api_router.include_router(admin_router, prefix="/admin", tags=["admin"])
api_router.include_router(upload_router, prefix="/upload", tags=["upload"])
api_router.include_router(ws_router, prefix="/ws", tags=["websocket"])
