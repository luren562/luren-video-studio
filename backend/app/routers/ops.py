from fastapi import APIRouter, Depends

from ..ops_service import system_health
from ..security import require_admin

router = APIRouter(prefix="/api/ops", dependencies=[Depends(require_admin)])


@router.get("/health")
def ops_health() -> dict:
    """系统巡检：DB / 磁盘 / 工具链 / 引擎接入 / 队列 / ASR。"""
    return system_health()
