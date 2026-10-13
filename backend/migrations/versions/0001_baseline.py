"""baseline：与当前 SQLAlchemy 模型一致的初始结构。

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-30

用 `Base.metadata.create_all` 生成全部表：此后模型变更请用
`alembic revision --autogenerate -m "..."` 生成独立修订，不要改本文件。
"""

from __future__ import annotations

from alembic import op

from app import models  # noqa: F401  注册全部表
from app.admin import AdminUser  # noqa: F401
from app.database import Base

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
