from datetime import datetime
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# 鉴权
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


# ---------------------------------------------------------------------------
# AI 配置
# ---------------------------------------------------------------------------
class AIProviderCreate(BaseModel):
    name: str
    base_url: str
    api_key: str = ""
    is_active: bool = True
    # 可选：建供应商时顺带建一个文本模型（避免「只有供应商没有模型」导致无法测试/生成）
    default_model_id: str = ""


class AIProviderUpdate(BaseModel):
    base_url: str | None = None
    api_key: str | None = None  # 空字符串 = 保留原值
    is_active: bool | None = None


class AIProviderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    base_url: str
    has_api_key: bool = False
    is_active: bool
    created_at: datetime


class AIModelCreate(BaseModel):
    provider_id: int
    name: str
    model_id: str
    capability: str = "text"
    config_json: dict = Field(default_factory=dict)
    is_active: bool = True


class AIModelUpdate(BaseModel):
    name: str | None = None
    model_id: str | None = None
    capability: str | None = None
    config_json: dict | None = None
    is_active: bool | None = None


class AIModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_id: int
    name: str
    model_id: str
    capability: str
    config_json: dict
    is_active: bool
    created_at: datetime


class CoverConfigRead(BaseModel):
    base_url: str = ""
    has_api_key: bool = False
    model: str = ""
    size: str = ""


class CoverConfigUpdate(BaseModel):
    base_url: str = Field(default="", max_length=500)
    api_key: str | None = None  # 留空=保留已存密钥
    model: str = Field(default="", max_length=200)
    size: str = Field(default="", max_length=40)


class ProviderTestResult(BaseModel):
    ok: bool
    model: str = ""
    latency_ms: int = 0
    error_type: str = ""
    message: str = ""


# ---------------------------------------------------------------------------
# 创作策略
# ---------------------------------------------------------------------------
class ContentStrategyCreate(BaseModel):
    name: str
    description: str = ""
    audience: str = ""
    tone: str = ""
    content_goal: str = ""
    prompt_rules: str = ""
    banned_phrases: list[str] = Field(default_factory=list)
    style_guide_md: str = ""
    default_model_id: int | None = None
    is_default: bool = False
    is_active: bool = True


class ContentStrategyUpdate(BaseModel):
    description: str | None = None
    audience: str | None = None
    tone: str | None = None
    content_goal: str | None = None
    prompt_rules: str | None = None
    banned_phrases: list[str] | None = None
    style_guide_md: str | None = None
    default_model_id: int | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class ContentStrategyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    audience: str
    tone: str
    content_goal: str
    prompt_rules: str
    banned_phrases_json: list
    style_guide_md: str
    default_model_id: int | None
    is_default: bool
    is_active: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# 风格档
# ---------------------------------------------------------------------------
class VideoStyleCreate(BaseModel):
    name: str
    engine: str
    aspect: str = "16:9"
    lang: str = "zh"
    default_duration_sec: int = 240
    theme_json: dict = Field(default_factory=dict)
    engine_config_json: dict = Field(default_factory=dict)
    is_active: bool = True


class VideoStyleUpdate(BaseModel):
    name: str | None = None
    aspect: str | None = None
    lang: str | None = None
    default_duration_sec: int | None = None
    theme_json: dict | None = None
    engine_config_json: dict | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class VideoStyleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    engine: str
    aspect: str
    lang: str
    default_duration_sec: int
    theme_json: dict
    engine_config_json: dict
    is_default: bool
    is_active: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# 项目 / 版本 / 场景
# ---------------------------------------------------------------------------
class ProjectAudioTheme(BaseModel):
    theme_json: dict[str, str] | None = None
    bgm_enabled: bool | None = None
    tts_enabled: bool | None = None
    tts_voice: str | None = Field(default=None, max_length=120)
    tts_rate: int | None = Field(default=None, ge=-50, le=50)
    tts_asset_id: int | None = Field(default=None, gt=0)

    @field_validator("theme_json")
    @classmethod
    def validate_theme(cls, value):
        if value is not None and (set(value) - {"accent"} or any(
            not re.fullmatch(r"#[0-9a-fA-F]{6}", color) for color in value.values()
        )):
            raise ValueError("主题色仅支持 accent，格式必须为 #RRGGBB")
        return value

    @field_validator("tts_voice")
    @classmethod
    def normalize_voice(cls, value):
        return value.strip() or None if value is not None else None


class VideoProjectCreate(ProjectAudioTheme):
    tts_enabled: bool = True
    topic: str
    title: str = ""
    audience: str = ""
    goal: str = ""
    source_notes: str = ""
    constraints: str = ""
    reference_url: str = ""
    style_id: int | None = None
    model_id: int | None = None
    strategy_id: int | None = None
    duration_target_sec: int | None = None
    lang: str | None = None
    review_required: bool = True


class VideoProjectRegenerate(ProjectAudioTheme):
    # 允许在重生成时覆盖需求字段
    topic: str | None = None
    title: str | None = None
    audience: str | None = None
    goal: str | None = None
    source_notes: str | None = None
    constraints: str | None = None
    reference_url: str | None = None
    style_id: int | None = None
    model_id: int | None = None
    duration_target_sec: int | None = None
    lang: str | None = None
    review_required: bool | None = None


class VideoSceneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_id: int
    position: int
    role: str
    narration_text: str
    subtitle_chunks_json: list
    visual_type: str
    card_slug: str
    content_json: dict
    asset_ids_json: list
    skinning: str
    render_status: str
    render_error: str


class VideoVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    version_number: int
    model_id: int | None
    prompt_version: str
    spec_json: dict
    generation_meta_json: dict
    validation_json: dict
    created_at: datetime
    scenes: list[VideoSceneRead] = Field(default_factory=list)


class VideoProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    topic: str
    audience: str
    goal: str
    source_notes: str
    constraints: str
    reference_url: str
    style_id: int | None
    model_id: int | None
    strategy_id: int | None
    mode: str
    duration_target_sec: int
    lang: str
    review_required: bool = True
    theme_json: dict | None = None
    bgm_enabled: bool | None = None
    tts_enabled: bool | None = None
    tts_voice: str | None = None
    tts_rate: int | None = None
    tts_asset_id: int | None = None
    status: str
    current_version_id: int | None
    error_message: str
    created_at: datetime
    updated_at: datetime


class VideoProjectDetail(VideoProjectRead):
    current_version: VideoVersionRead | None = None
    latest_task_id: int | None = None
    agent_summary: "AgentRunSummary | None" = None


class AgentRunSummary(BaseModel):
    """Agent 运行摘要；保留扩展字段以兼容旧 checkpoint 和新 usage 网关字段。"""

    model_config = ConfigDict(extra="allow")

    phase: str = "plan"
    phase_label: str = "确定方案"
    iteration: int = 0
    max_iters: int = 0
    status: str = ""
    usage: dict = Field(default_factory=dict)
    candidate_count: int = 0
    inspections: int = 0
    render_attempts: int = 0
    last_tool: str = ""
    last_tool_at: float | None = None
    updated_at: float | None = None
    schema_version: int = 1
    execution_id: str | None = None
    invocation_id: str | None = None
    budget_scope: str = "legacy_unknown"
    invocation_usage: dict = Field(default_factory=dict)
    unknown_usage_responses: int = 0
    remaining_seconds: int = 0
    stop_reason: dict | None = None
    blockers: list[str] = Field(default_factory=list)
    last_progress: dict | None = None
    work_summary: dict = Field(default_factory=dict)
    candidate_status: str = "unknown"
    convergence_mode: bool = False
    still_qa: dict = Field(default_factory=dict)
    visual_qa: dict = Field(default_factory=dict)
    still_reviews: int = 0
    render_ledger: list = Field(default_factory=list)
    granted_renders: int = 0
    render_concurrency: int | None = None
    render_concurrency_reason: str = ''
    check_ready_last: dict = Field(default_factory=dict)


VideoProjectDetail.model_rebuild()


# ---------------------------------------------------------------------------
# 任务 / 素材 / 成片
# ---------------------------------------------------------------------------
class PipelineEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    level: str
    message: str
    data_json: dict
    created_at: datetime


class PipelineTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    resource_type: str
    resource_id: int | None
    status: str
    progress_current: int
    progress_total: int
    attempts: int
    max_attempts: int
    error_code: str
    error_message: str
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MediaAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_type: str
    filename: str
    path: str
    mime: str
    sha256: str
    size_bytes: int | None
    width: int | None
    height: int | None
    duration_sec: float | None
    metadata_json: dict
    created_at: datetime


class TranscriptionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    source_type: str
    source_ref: str
    language: str
    model: str
    status: str
    duration_sec: float | None
    error_message: str
    created_at: datetime
    updated_at: datetime


class TranscriptionRead(TranscriptionSummary):
    text: str
    segments_json: list


class TranscriptionCreateUrl(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    language: str = Field(default="zh", max_length=8)
    title: str = Field(default="", max_length=300)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip()
        if not value.lower().startswith(("http://", "https://")):
            raise ValueError("仅支持 http/https 视频直链")
        return value

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        value = (value or "zh").strip().lower()
        return value if value in ("zh", "en", "auto") else "zh"


class RenderOutputRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    version_id: int
    engine: str
    width: int
    height: int
    fps: int
    duration_frames: int
    file_path: str
    poster_path: str
    contact_sheet_path: str
    cover_path: str = ""
    cover_status: str = ""
    cover_error: str = ""
    sha256: str
    status: str
    gates_json: dict
    review_json: dict
    created_at: datetime


class StatsRead(BaseModel):
    projects_total: int
    projects_in_progress: int
    outputs_total: int
    outputs_completed: int
    tasks_queued: int
    tasks_running: int
    tasks_failed: int
