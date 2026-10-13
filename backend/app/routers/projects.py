from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import get_settings
from ..tts_providers import resolve_voice, TtsError
from ..models import MediaAsset, PipelineEvent, PipelineTask, RenderOutput, ReviewDecision, VideoProject, VideoStyle, VideoVersion
from ..schemas import (
    VideoProjectCreate,
    VideoProjectDetail,
    VideoProjectRead,
    VideoProjectRegenerate,
    VideoVersionRead,
)
from ..security import require_admin
from ..services import enqueue_task, project_to_detail, version_to_read

router = APIRouter(prefix="/api/projects", dependencies=[Depends(require_admin)])


def validate_narration_asset(db: Session, asset_id: int | None) -> None:
    if asset_id is None:
        return
    from pathlib import Path
    asset = db.get(MediaAsset, asset_id)
    if not asset or not asset.mime.startswith("audio/") or not Path(asset.path).is_file():
        raise HTTPException(status_code=422, detail="请选择已上传的有效旁白音频")


def validate_voice(voice: str | None) -> None:
    if voice:
        try:
            resolve_voice(get_settings().tts_provider, voice, get_settings())
        except TtsError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=list[VideoProjectRead])
def list_projects(
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[VideoProject]:
    stmt = select(VideoProject).order_by(VideoProject.created_at.desc())
    if status:
        stmt = stmt.where(VideoProject.status == status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(VideoProject.topic.like(like) | VideoProject.title.like(like))
    return list(db.scalars(stmt).all())


@router.post("", response_model=VideoProjectDetail, status_code=201)
def create_project(payload: VideoProjectCreate, db: Session = Depends(get_db)) -> VideoProjectDetail:
    validate_narration_asset(db, payload.tts_asset_id)
    validate_voice(payload.tts_voice)
    style = None
    if payload.style_id:
        style = db.get(VideoStyle, payload.style_id)
        if style is None:
            raise HTTPException(status_code=404, detail="风格档不存在")
    else:
        style = db.scalar(select(VideoStyle).where(VideoStyle.is_default.is_(True)))
        if style is None:
            style = db.scalar(select(VideoStyle).where(VideoStyle.is_active.is_(True)))

    project = VideoProject(
        title=payload.title,
        topic=payload.topic,
        audience=payload.audience,
        goal=payload.goal,
        source_notes=payload.source_notes,
        constraints=payload.constraints,
        reference_url=payload.reference_url,
        style_id=style.id if style else payload.style_id,
        model_id=payload.model_id,
        strategy_id=payload.strategy_id,
        mode="agent",
        duration_target_sec=payload.duration_target_sec
        or (style.default_duration_sec if style else 240),
        lang=payload.lang or (style.lang if style else "zh"),
        review_required=payload.review_required,
        theme_json=payload.theme_json or {},
        bgm_enabled=payload.bgm_enabled,
        tts_enabled=payload.tts_enabled,
        tts_voice=payload.tts_voice,
        tts_rate=payload.tts_rate,
        tts_asset_id=payload.tts_asset_id,
        status="generating",
    )
    db.add(project)
    db.flush()
    enqueue_task(
        db,
        kind="agent_film",
        resource_type="project",
        resource_id=project.id,
        payload={"project_id": project.id},
        max_attempts=1,
    )
    db.commit()
    db.refresh(project)
    return project_to_detail(db, project)


@router.get("/{project_id}", response_model=VideoProjectDetail)
def get_project(project_id: int, db: Session = Depends(get_db)) -> VideoProjectDetail:
    project = db.get(VideoProject, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project_to_detail(db, project)


@router.post("/{project_id}/regenerate", response_model=VideoProjectDetail)
def regenerate_project(
    project_id: int, payload: VideoProjectRegenerate, db: Session = Depends(get_db)
) -> VideoProjectDetail:
    project = db.get(VideoProject, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    active_task = db.scalar(select(PipelineTask.id).where(
        PipelineTask.kind == "agent_film",
        PipelineTask.resource_type == "project",
        PipelineTask.resource_id == project_id,
        PipelineTask.status.in_(["queued", "running"]),
    ))
    if active_task is not None:
        raise HTTPException(status_code=409, detail="该项目已有排队或运行中的任务，请完成或取消后再重生成")
    validate_narration_asset(db, payload.tts_asset_id)
    validate_voice(payload.tts_voice)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None or key in {"theme_json", "bgm_enabled", "tts_enabled", "tts_voice", "tts_rate", "tts_asset_id"}:
            setattr(project, key, value)
    project.status = "generating"
    project.error_message = ""
    project.mode = "agent"
    enqueue_task(
        db,
        kind="agent_film",
        resource_type="project",
        resource_id=project.id,
        payload={"project_id": project.id},
        max_attempts=1,
    )
    db.commit()
    db.refresh(project)
    return project_to_detail(db, project)


@router.get("/{project_id}/versions", response_model=list[VideoVersionRead])
def list_versions(project_id: int, db: Session = Depends(get_db)) -> list[VideoVersionRead]:
    versions = db.scalars(
        select(VideoVersion)
        .where(VideoVersion.project_id == project_id)
        .order_by(VideoVersion.version_number.desc())
    ).all()
    return [version_to_read(db, v) for v in versions]


@router.post("/{project_id}/submit-review", response_model=VideoProjectDetail)
def submit_review(project_id: int, db: Session = Depends(get_db)) -> VideoProjectDetail:
    project = db.get(VideoProject, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not project.current_version_id:
        raise HTTPException(status_code=422, detail="尚未生成规格，无法提交审核")
    project.status = "pending_review"
    db.add(
        ReviewDecision(
            project_id=project.id,
            version_id=project.current_version_id,
            decision="submitted",
        )
    )
    db.commit()
    db.refresh(project)
    return project_to_detail(db, project)


@router.post("/{project_id}/approve", response_model=VideoProjectDetail)
def approve(project_id: int, db: Session = Depends(get_db)) -> VideoProjectDetail:
    project = db.get(VideoProject, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not project.current_version_id:
        raise HTTPException(status_code=422, detail="尚未生成规格")
    project.status = "approved"
    db.add(
        ReviewDecision(
            project_id=project.id,
            version_id=project.current_version_id,
            decision="approved",
        )
    )
    # Agent 模式的审核节点审核的是规格/分镜。通过后如果当前版本还没有
    # 可交付成片，自动接续同一版本的 Agent 任务，避免项目停在 approved
    # 但没有任何可执行入口的状态。
    if project.mode == "agent":
        deliverable = db.scalar(
            select(RenderOutput.id).where(
                RenderOutput.project_id == project.id,
                RenderOutput.version_id == project.current_version_id,
                RenderOutput.status.in_(["gates_passed", "reviewed", "completed"]),
            )
        )
        active_agent_task = db.scalar(
            select(PipelineTask.id).where(
                PipelineTask.kind == "agent_film",
                PipelineTask.resource_type == "project",
                PipelineTask.resource_id == project.id,
                PipelineTask.status.in_(["queued", "running"]),
            )
        )
        if not deliverable and not active_agent_task:
            enqueue_task(
                db,
                kind="agent_film",
                resource_type="project",
                resource_id=project.id,
                payload={"project_id": project.id, "agent_version_id": project.current_version_id},
                max_attempts=1,
            )
            project.status = "rendering"
            project.error_message = "审核通过，正在继续 Agent 精修"
    db.commit()
    db.refresh(project)
    return project_to_detail(db, project)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)) -> None:
    project = db.get(VideoProject, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    version_ids = list(db.scalars(select(VideoVersion.id).where(VideoVersion.project_id == project_id)).all())
    conditions = [and_(PipelineTask.resource_type == "project", PipelineTask.resource_id == project_id)]
    if version_ids:
        conditions.append(and_(PipelineTask.resource_type == "version", PipelineTask.resource_id.in_(version_ids)))
    output_ids = select(RenderOutput.id).where(RenderOutput.project_id == project_id)
    conditions.append(and_(PipelineTask.resource_type == "output", PipelineTask.resource_id.in_(output_ids)))
    # 先清掉该项目（及其版本）的任务与事件，避免删项目后残留任务把它卡住
    tasks = db.scalars(select(PipelineTask).where(or_(*conditions))).all()
    for task in tasks:
        db.query(PipelineEvent).filter(PipelineEvent.task_id == task.id).delete(synchronize_session=False)
        db.delete(task)
    db.flush()
    db.delete(project)
    db.commit()
