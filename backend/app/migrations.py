"""数据库迁移：Alembic 正式迁移（批次 A）。

`upgrade_database()` 走 `alembic upgrade head`：
- 全新库：跑基线修订建表；
- 既有 `create_all` 建的库（有表、无 alembic_version）：先认 0001 基线，再运行增量迁移；
- 未安装 alembic 时降级回 `Base.metadata.create_all`。

模型变更流程：`alembic revision --autogenerate -m "..."`（env.py 已接模型 metadata）。
"""

from pathlib import Path

from sqlalchemy import inspect, select

from . import models  # noqa: F401  (注册全部表)
from .admin import AdminUser  # noqa: F401
from .config import get_settings
from .database import Base, SessionLocal, engine
from .engine_registry import DEFAULT_STYLES
from .models import ContentStrategy, VideoStyle
from .style_presets import PRESET_STRATEGIES

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic_config():
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    return config


def upgrade_database() -> None:
    try:
        from alembic import command
    except Exception:  # noqa: BLE001  alembic 未装 → 退回 create_all
        Base.metadata.create_all(bind=engine)
        return

    config = _alembic_config()
    tables = set(inspect(engine).get_table_names())
    if "alembic_version" not in tables and (tables & set(Base.metadata.tables.keys())):
        # 既有 create_all 库：把基线标记为已应用，避免重复建表报错
        command.stamp(config, "0001_baseline")
    command.upgrade(config, "head")


ALLOWED_ENGINES = {"shotcraft", "talkcraft"}


def seed_defaults() -> None:
    with SessionLocal() as session:
        # 下线未注册引擎的旧风格档（保留 shotcraft / talkcraft）
        for style in session.scalars(select(VideoStyle)).all():
            if style.engine not in ALLOWED_ENGINES:
                session.delete(style)
        existing_names = set(session.scalars(select(VideoStyle.name)).all())
        for style in DEFAULT_STYLES:
            if style["name"] not in existing_names:
                session.add(VideoStyle(**style))
        # 内置作者风格画像（按 name 幂等；schema 用 banned_phrases，模型字段是 banned_phrases_json）
        existing_strategies = {s.name: s for s in session.scalars(select(ContentStrategy)).all()}
        content_fields = (
            "description", "audience", "tone", "content_goal",
            "prompt_rules", "banned_phrases_json", "style_guide_md",
        )
        for preset in PRESET_STRATEGIES:
            data = dict(preset)
            data["banned_phrases_json"] = data.pop("banned_phrases", [])
            strategy = existing_strategies.get(preset["name"])
            if strategy is None:
                session.add(ContentStrategy(**data))
                continue
            # 内置预设正文以代码为准：刷新内容字段，保留 is_default / is_active 等运行状态。
            for field_name in content_fields:
                setattr(strategy, field_name, data[field_name])
        session.commit()
