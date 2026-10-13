from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# ---------------------------------------------------------------------------
# AI 配置
# ---------------------------------------------------------------------------
class AIProvider(TimestampMixin, Base):
    __tablename__ = "ai_providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    base_url: Mapped[str] = mapped_column(String(500))
    encrypted_api_key: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    models: Mapped[list["AIModel"]] = relationship(back_populates="provider")


class AIModel(TimestampMixin, Base):
    __tablename__ = "ai_models"
    __table_args__ = (UniqueConstraint("provider_id", "model_id", name="uq_provider_model"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("ai_providers.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    model_id: Mapped[str] = mapped_column(String(200))
    capability: Mapped[str] = mapped_column(String(20), default="text")  # text|vision|agent|tts|asr|image
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    provider: Mapped[AIProvider] = relationship(back_populates="models")


class ContentStrategy(TimestampMixin, Base):
    __tablename__ = "content_strategies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(Text, default="")
    tone: Mapped[str] = mapped_column(Text, default="")
    content_goal: Mapped[str] = mapped_column(Text, default="")
    prompt_rules: Mapped[str] = mapped_column(Text, default="")
    banned_phrases_json: Mapped[list] = mapped_column(JSON, default=list)
    # 作者风格画像全文（Markdown）：生成时写入工作区 .opencode/platform/style.md
    style_guide_md: Mapped[str] = mapped_column(Text, default="")
    default_model_id: Mapped[int | None] = mapped_column(ForeignKey("ai_models.id"))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------------------
# 风格档（引擎预设）
# ---------------------------------------------------------------------------
class VideoStyle(TimestampMixin, Base):
    __tablename__ = "video_styles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    engine: Mapped[str] = mapped_column(String(30))  # explainer|talkcraft|shotcraft
    aspect: Mapped[str] = mapped_column(String(10), default="16:9")  # 16:9|9:16
    lang: Mapped[str] = mapped_column(String(8), default="zh")  # zh|en
    default_duration_sec: Mapped[int] = mapped_column(Integer, default=240)
    theme_json: Mapped[dict] = mapped_column(JSON, default=dict)
    engine_config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------------------
# 项目 / 版本 / 场景
# ---------------------------------------------------------------------------
class VideoProject(TimestampMixin, Base):
    __tablename__ = "video_projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    topic: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(Text, default="")
    goal: Mapped[str] = mapped_column(Text, default="")
    source_notes: Mapped[str] = mapped_column(Text, default="")
    constraints: Mapped[str] = mapped_column(Text, default="")
    reference_url: Mapped[str] = mapped_column(String(1000), default="")
    style_id: Mapped[int | None] = mapped_column(ForeignKey("video_styles.id"))
    model_id: Mapped[int | None] = mapped_column(ForeignKey("ai_models.id"))
    strategy_id: Mapped[int | None] = mapped_column(ForeignKey("content_strategies.id"))
    mode: Mapped[str] = mapped_column(String(20), default="structured")  # structured|hybrid|agent
    duration_target_sec: Mapped[int] = mapped_column(Integer, default=240)
    lang: Mapped[str] = mapped_column(String(8), default="zh")
    # 是否需要视觉审片：关闭时 agent 直接产出，跳过静帧预审与终审（技术闸照常）。
    review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    theme_json: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    bgm_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tts_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tts_voice: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tts_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 语速百分数 -100~100；空=继承全局
    tts_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # generating|spec_ready|pending_review|approved|rendering|rendered|completed|failed|needs_attention
    status: Mapped[str] = mapped_column(String(30), default="generating")
    current_version_id: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(120), default="")


class VideoVersion(Base):
    __tablename__ = "video_versions"
    __table_args__ = (UniqueConstraint("project_id", "version_number", name="uq_project_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("video_projects.id", ondelete="CASCADE"))
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    model_id: Mapped[int | None] = mapped_column(Integer)
    prompt_version: Mapped[str] = mapped_column(String(50), default="v1")
    spec_json: Mapped[dict] = mapped_column(JSON, default=dict)
    generation_input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    generation_meta_json: Mapped[dict] = mapped_column(JSON, default=dict)
    validation_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VideoScene(TimestampMixin, Base):
    __tablename__ = "video_scenes"
    __table_args__ = (UniqueConstraint("version_id", "position", name="uq_version_position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("video_versions.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(30), default="content")
    narration_text: Mapped[str] = mapped_column(Text, default="")
    subtitle_chunks_json: Mapped[list] = mapped_column(JSON, default=list)
    visual_type: Mapped[str] = mapped_column(String(30), default="card")
    card_slug: Mapped[str] = mapped_column(String(120), default="")
    content_json: Mapped[dict] = mapped_column(JSON, default=dict)
    asset_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    skinning: Mapped[str] = mapped_column(Text, default="")
    render_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|rendering|succeeded|failed
    render_error: Mapped[str] = mapped_column(Text, default="")


# ---------------------------------------------------------------------------
# AI 主题封面（独立配置，单例；与 ai_models 生产模型解耦）
# ---------------------------------------------------------------------------
class CoverConfig(TimestampMixin, Base):
    __tablename__ = "cover_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    base_url: Mapped[str] = mapped_column(String(500), default="")  # OpenAI 兼容生图网关
    encrypted_api_key: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(200), default="")  # 生图模型名
    size: Mapped[str] = mapped_column(String(40), default="")  # 如 1792x1024；空=按画布比例


# ---------------------------------------------------------------------------
# 视频/音频转文稿
# ---------------------------------------------------------------------------
class TranscriptionJob(TimestampMixin, Base):
    __tablename__ = "transcription_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    source_type: Mapped[str] = mapped_column(String(20), default="upload")  # upload|url
    source_ref: Mapped[str] = mapped_column(String(2000), default="")  # 文件名或直链
    media_path: Mapped[str] = mapped_column(String(1000), default="")
    language: Mapped[str] = mapped_column(String(8), default="zh")  # zh|en|auto
    model: Mapped[str] = mapped_column(String(40), default="")
    # queued|running|succeeded|failed
    status: Mapped[str] = mapped_column(String(20), default="queued")
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")
    segments_json: Mapped[list] = mapped_column(JSON, default=list)
    text_path: Mapped[str] = mapped_column(String(1000), default="")
    srt_path: Mapped[str] = mapped_column(String(1000), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(120), default="")


# ---------------------------------------------------------------------------
# 素材
# ---------------------------------------------------------------------------
class MediaAsset(TimestampMixin, Base):
    __tablename__ = "media_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    # upload|tts|broll|screenshot|bgm|sfx|icon|render|poster|contact_sheet
    source_type: Mapped[str] = mapped_column(String(30), default="upload")
    filename: Mapped[str] = mapped_column(String(500), default="")
    path: Mapped[str] = mapped_column(String(1000), default="")
    mime: Mapped[str] = mapped_column(String(100), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="", index=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------------------
# 任务队列
# ---------------------------------------------------------------------------
class PipelineTask(TimestampMixin, Base):
    __tablename__ = "pipeline_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))  # generate_spec|generate_assets|tts|render|assemble|qa
    resource_type: Mapped[str] = mapped_column(String(40), default="")
    resource_id: Mapped[int | None] = mapped_column(Integer)
    # queued|running|succeeded|failed|cancelled
    status: Mapped[str] = mapped_column(String(20), default="queued")
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str] = mapped_column(String(50), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("pipeline_tasks.id", ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String(20), default="info")
    message: Mapped[str] = mapped_column(Text, default="")
    data_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------------------
# 审片 / 成片
# ---------------------------------------------------------------------------
class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("video_projects.id", ondelete="CASCADE"))
    version_id: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(20))  # submitted|approved|rejected
    comment: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RenderOutput(TimestampMixin, Base):
    __tablename__ = "render_outputs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("video_projects.id", ondelete="CASCADE"))
    version_id: Mapped[int] = mapped_column(Integer)
    engine: Mapped[str] = mapped_column(String(30), default="explainer")
    width: Mapped[int] = mapped_column(Integer, default=1920)
    height: Mapped[int] = mapped_column(Integer, default=1080)
    fps: Mapped[int] = mapped_column(Integer, default=30)
    duration_frames: Mapped[int] = mapped_column(Integer, default=0)
    file_path: Mapped[str] = mapped_column(String(1000), default="")
    poster_path: Mapped[str] = mapped_column(String(1000), default="")
    contact_sheet_path: Mapped[str] = mapped_column(String(1000), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    # draft|rendering|gates_failed|gates_passed|reviewed|completed|failed
    status: Mapped[str] = mapped_column(String(20), default="rendering")
    gates_json: Mapped[dict] = mapped_column(JSON, default=dict)
    review_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # AI 主题封面：空路径=未生成；status: ""|queued|running|ready|failed
    cover_path: Mapped[str] = mapped_column(String(1000), default="")
    cover_status: Mapped[str] = mapped_column(String(20), default="")
    cover_error: Mapped[str] = mapped_column(Text, default="")


class EngineRun(Base):
    __tablename__ = "engine_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("video_projects.id", ondelete="CASCADE"))
    engine: Mapped[str] = mapped_column(String(30), default="")
    stage: Mapped[str] = mapped_column(String(40), default="")
    command: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="running")
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    log_path: Mapped[str] = mapped_column(String(1000), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
