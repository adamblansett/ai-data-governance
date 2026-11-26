from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.connectors import router as connectors_router
from app.api.v1.dedup import router as dedup_router
from app.api.v1.governance import router as governance_router
from app.api.v1.health import router as health_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.normalizers import router as normalizers_router
from app.api.v1.pii import router as pii_router
from app.api.v1.reports import router as reports_router
from app.api.v1.schema_audit import router as schema_audit_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(pii_router)
api_v1_router.include_router(dedup_router)
api_v1_router.include_router(normalizers_router)
api_v1_router.include_router(schema_audit_router)
api_v1_router.include_router(connectors_router)
api_v1_router.include_router(jobs_router)
api_v1_router.include_router(reports_router)
api_v1_router.include_router(governance_router)
