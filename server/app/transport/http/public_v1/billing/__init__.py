from app.transport.http.public_v1.billing.checkout import router as checkout_router
from app.transport.http.public_v1.billing.interval import router as interval_router
from app.transport.http.public_v1.billing.portal import router as portal_router
from app.transport.http.public_v1.billing.status import router as status_router
from fastapi import APIRouter

subscription_router = APIRouter()
subscription_router.include_router(checkout_router)
subscription_router.include_router(status_router)
subscription_router.include_router(portal_router)
subscription_router.include_router(interval_router)
