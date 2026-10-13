"""transcription_jobs (视频/音频转文稿)."""
import sqlalchemy as sa
from alembic import op

revision = "0006_transcription_jobs"
down_revision = "0005_content_strategy_style_guide"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    if _has_table("transcription_jobs"):
        return
    op.create_table(
        "transcription_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(300), nullable=False, server_default=""),
        sa.Column("source_type", sa.String(20), nullable=False, server_default="upload"),
        sa.Column("source_ref", sa.String(2000), nullable=False, server_default=""),
        sa.Column("media_path", sa.String(1000), nullable=False, server_default=""),
        sa.Column("language", sa.String(8), nullable=False, server_default="zh"),
        sa.Column("model", sa.String(40), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("segments_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("text_path", sa.String(1000), nullable=False, server_default=""),
        sa.Column("srt_path", sa.String(1000), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(120), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    if _has_table("transcription_jobs"):
        op.drop_table("transcription_jobs")
