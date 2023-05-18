from app.api.utils import APIRouter

from app.api.endpoints import ping, recognize, enhancement, separate

api_router = APIRouter()
api_router.include_router(ping.router, prefix="/ping", tags=["ping"])
api_router.include_router(recognize.router, prefix="/recognize", tags=["recognize"])
api_router.include_router(enhancement.router, prefix="/enhancement", tags=["enhancement"])
api_router.include_router(separate.router, prefix="/separate", tags=["separate"])
