"""AI theme cover: render output cover columns.

- render_outputs.cover_path/status/error  AI 主题封面产物与状态
（封面模型改为独立单例配置，见 0009_cover_config）
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_render_cover"
down_revision = "0007_project_tts_rate"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if "render_outputs" not in _tables():
        return
    existing = _columns("render_outputs")
    if "cover_path" not in existing:
        op.add_column("render_outputs", sa.Column("cover_path", sa.String(1000), nullable=False, server_default=""))
    if "cover_status" not in existing:
        op.add_column("render_outputs", sa.Column("cover_status", sa.String(20), nullable=False, server_default=""))
    if "cover_error" not in existing:
        op.add_column("render_outputs", sa.Column("cover_error", sa.Text(), nullable=False, server_default=""))


def downgrade():
    if "render_outputs" not in _tables():
        return
    existing = _columns("render_outputs")
    with op.batch_alter_table("render_outputs") as batch:
        for name in ("cover_error", "cover_status", "cover_path"):
            if name in existing:
                batch.drop_column(name)
