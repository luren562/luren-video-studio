from functools import lru_cache
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / ".env", PROJECT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Video Foundry Backend"

    # --- 数据库 ---
    database_url: str = f"sqlite:///{(DATA_DIR / 'backend.db').as_posix()}"

    # --- 鉴权 ---
    jwt_secret: str = "development-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480
    fernet_key: str = ""
    admin_username: str = "admin"
    admin_password: str = "123456"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"]
    )

    # --- Worker ---
    worker_enabled: bool = True
    worker_poll_seconds: float = Field(default=2.0, ge=0.1)
    pipeline_worker_enabled: bool = True
    pipeline_poll_seconds: float = Field(default=1.0, ge=0.1)
    pipeline_lease_seconds: int = Field(default=600, ge=10)
    pipeline_reset_running_on_start: bool = True  # 单机单 worker：启动时回收残留 running 任务
    node_binary: str = "node"
    ffmpeg_binary: str = "ffmpeg"
    # 引擎原生渲染（Remotion）的帧并发；可在「设置」页运行时覆盖并持久化。
    render_concurrency: int = Field(default=1, ge=1, le=16)
    render_timeout_seconds: int = Field(default=1800, ge=30)

    # --- Agent（opencode headless 单模式）---
    agent_skill_dirname: str = "video-shotcraft"  # engines/ 下挂载的 skill 仓库
    agent_model_capability: str = "text"  # 未指定项目模型时的制作模型能力
    agent_review_model_capability: str = "vision"
    agent_wall_seconds: int = Field(default=3600, ge=120)  # 单项目墙钟上限
    # opencode `question` 工具策略：deny=拒绝提问（默认，避免无人回答时空转到墙钟）；
    # ask/wait 保留提问通道（需平台侧具备回答入口）。
    agent_question_policy: Literal["deny", "ask", "wait"] = "deny"
    agent_render_timeout_seconds: int = Field(default=1800, ge=60)

    # --- opencode headless 运行器 ---
    opencode_binary: str = "opencode"
    opencode_version: str = ""  # 仅记录/校验；空=不校验
    opencode_hostname: str = "127.0.0.1"
    opencode_port: int = Field(default=0, ge=0, le=65535)  # 0=自动选空闲端口
    opencode_server_password: str = ""  # 空=每次运行自动生成
    opencode_provider_id: str = "vf"  # opencode 自定义 provider id（OpenAI 兼容网关）
    opencode_start_timeout_seconds: int = Field(default=120, ge=5)
    opencode_poll_seconds: float = Field(default=2.0, ge=0.25)
    opencode_event_reconnect_seconds: float = Field(default=3.0, ge=0.5)

    # --- TTS（配音）---
    tts_enabled: bool = True
    tts_provider: Literal["edge", "manual"] = "edge"
    tts_fallback: Literal["manual", "none"] = "none"
    tts_required: bool = False  # 合成失败时是否阻塞渲染
    tts_engine: str = "edge"
    tts_voice_zh: str = "zh-CN-YunxiNeural"
    tts_voice_en: str = "en-US-AndrewNeural"
    tts_rate: str = "+0%"
    tts_retries: int = Field(default=8, ge=1, le=20)  # 每句 edge-tts 重试次数（网络间歇性失败）
    tts_proxy: str = ""  # 走代理时填 http://host:port（edge-tts 不自动读系统代理）
    # 强制 IPv4：aiohttp 默认双栈会随机选到不可达的 IPv6，报「指定的网络名不再可用」；
    # 实测强制 AF_INET 后 edge-tts 稳定（本机 20/20 vs 默认 ~35% 成功率）。
    tts_force_ipv4: bool = True
    tts_lead_frames: int = Field(default=12, ge=0)
    tts_gap_frames: int = Field(default=12, ge=0)
    tts_chapter_gap_frames: int = Field(default=30, ge=0)
    tts_tail_frames: int = Field(default=45, ge=0)
    tts_timeout_seconds: int = Field(default=600, ge=10)

    # --- 主题封面（AI 生图，OpenAI 兼容 /images/generations）---
    cover_enabled: bool = True  # 全局开关：关闭后渲染成功不再自动生成封面
    cover_timeout_seconds: int = Field(default=180, ge=10)

    # --- 视频/音频转文稿（ASR）---
    transcribe_enabled: bool = True
    transcribe_model: str = "small"  # faster-whisper 模型：tiny/base/small/medium/large-v3
    transcribe_device: str = "cpu"  # cpu|cuda
    transcribe_compute_type: str = "int8"  # int8|int8_float16|float16|float32
    transcribe_language: str = "zh"  # zh|en|auto
    transcribe_max_download_mb: int = Field(default=2048, ge=1)
    transcribe_timeout_seconds: int = Field(default=7200, ge=60)

    # --- AI（文本/视觉模型网关）---
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    ai_allow_local_http: bool = False
    ai_connect_timeout_seconds: float = Field(default=10.0, gt=0)
    ai_read_timeout_seconds: float = Field(default=120.0, gt=0)
    ai_total_timeout_seconds: float = Field(default=180.0, gt=0)
    ai_max_response_bytes: int = Field(default=2_000_000, ge=1024)
    ai_retry_base_seconds: int = Field(default=5, ge=1, le=300)
    ai_retry_max_seconds: int = Field(default=60, ge=1, le=3600)

    # --- 目录 ---
    engines_dir: Path = PROJECT_DIR / "engines"
    data_dir: Path = DATA_DIR
    projects_dir: Path = DATA_DIR / "projects"
    assets_dir: Path = DATA_DIR / "assets"
    renders_dir: Path = DATA_DIR / "renders"
    uploads_dir: Path = DATA_DIR / "uploads"
    transcripts_dir: Path = DATA_DIR / "transcripts"
    logs_dir: Path = DATA_DIR / "logs"
    backup_dir: Path = DATA_DIR / "backups"
    cleanup_retention_days: int = Field(default=14, ge=1)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value):
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @property
    def effective_fernet_key(self) -> bytes:
        if self.fernet_key:
            return self.fernet_key.encode("ascii")
        import base64
        import hashlib

        digest = hashlib.sha256((self.jwt_secret + ":fernet").encode()).digest()
        return base64.urlsafe_b64encode(digest)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    Fernet(settings.effective_fernet_key)
    # 应用「设置」页写入的运行时覆盖（无则保持 env/默认）。
    from .runtime_settings import load_overrides

    for key, value in load_overrides(settings.data_dir).items():
        setattr(settings, key, value)
    return settings
