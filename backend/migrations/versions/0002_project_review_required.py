"""projects.review_required：是否启用视觉审片（默认开启，保持旧行为）。

Revision ID: 0002_review_required
Revises: 0001_baseline
Create Date: 2026-10-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0002_review_required"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns("video_projects")}


def upgrade() -> None:
    # 0001 基线用当前模型 create_all，全新库可能已带此列；重复加列会报错，先探测。
    if "review_required" in _columns():
        return
    op.add_column(
        "video_projects",
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    if "review_required" not in _columns():
        return
    with op.batch_alter_table("video_projects") as batch:
        batch.drop_column("review_required")
