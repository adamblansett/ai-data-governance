from fastapi import APIRouter

from app.api.v1.dedup import router as dedup_router
from app.api.v1.governance import router as governance_router
from app.api.v1.health import router as health_router
from app.api.v1.normalizers import router as normalizers_router
from app.api.v1.pii import router as pii_router
from app.api.v1.schema_audit import router as schema_audit_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(pii_router)
api_v1_router.include_router(dedup_router)
api_v1_router.include_router(normalizers_router)
api_v1_router.include_router(schema_audit_router)
api_v1_router.include_router(governance_router)
