"""Dedicated AI theme-cover model config (singleton) + drop legacy project column."""
import sqlalchemy as sa
from alembic import op

revision = "0009_cover_config"
down_revision = "0008_render_cover"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    tables = _tables()
    if "cover_config" not in tables:
        op.create_table(
            "cover_config",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("base_url", sa.String(500), nullable=False, server_default=""),
            sa.Column("encrypted_api_key", sa.Text(), nullable=False, server_default=""),
            sa.Column("model", sa.String(200), nullable=False, server_default=""),
            sa.Column("size", sa.String(40), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
    # 兼容早期试用版：清掉曾加到 video_projects 的封面模型外键列（不主张保留）。
    if "video_projects" in tables and "cover_model_id" in _columns("video_projects"):
        with op.batch_alter_table("video_projects") as batch:
            batch.drop_column("cover_model_id")


def downgrade():
    if "cover_config" in _tables():
        op.drop_table("cover_config")
