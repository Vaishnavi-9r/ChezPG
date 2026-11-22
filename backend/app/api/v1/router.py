from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.locations import router as locations_router
from app.api.v1.media import admin_router as admin_media_router
from app.api.v1.media import router as media_router
from app.api.v1.nearby_places import router as nearby_places_router
from app.api.v1.owners import management_router as owner_management_router
from app.api.v1.owners import router as owners_router
from app.api.v1.pgs import router as pgs_router
from app.api.v1.rooms import router as rooms_router
from app.api.v1.reviews import router as reviews_router
from app.api.v1.notifications import router as notifications_router

api_router = APIRouter()

api_router.include_router(locations_router)
api_router.include_router(auth_router)
api_router.include_router(pgs_router)
api_router.include_router(admin_router)
api_router.include_router(admin_media_router)
api_router.include_router(owners_router)
api_router.include_router(owner_management_router)
api_router.include_router(rooms_router)
api_router.include_router(reviews_router)
api_router.include_router(notifications_router)
api_router.include_router(media_router)
api_router.include_router(nearby_places_router)