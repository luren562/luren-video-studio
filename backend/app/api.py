from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .admin import AdminUser
from .database import get_db
from .models import PipelineTask, RenderOutput, VideoProject
from .schemas import LoginRequest, StatsRead, TokenResponse
from .security import create_access_token, require_admin, verify_password

router = APIRouter(prefix="/api")


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(AdminUser).where(AdminUser.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    return TokenResponse(access_token=create_access_token(user.username), username=user.username)


@router.get("/auth/me")
def me(username: str = Depends(require_admin)) -> dict:
    return {"username": username}


@router.get("/stats", response_model=StatsRead)
def stats(db: Session = Depends(get_db), _: str = Depends(require_admin)) -> StatsRead:
    def count(model, *where) -> int:
        stmt = select(func.count()).select_from(model)
        for cond in where:
            stmt = stmt.where(cond)
        return db.scalar(stmt) or 0

    return StatsRead(
        projects_total=count(VideoProject),
        projects_in_progress=count(
            VideoProject,
            VideoProject.status.in_(["generating", "rendering", "spec_ready", "approved"]),
        ),
        outputs_total=count(RenderOutput),
        outputs_completed=count(
            RenderOutput, RenderOutput.status.in_(["gates_passed", "reviewed", "completed"])
        ),
        tasks_queued=count(PipelineTask, PipelineTask.status == "queued"),
        tasks_running=count(PipelineTask, PipelineTask.status == "running"),
        tasks_failed=count(PipelineTask, PipelineTask.status == "failed"),
    )
