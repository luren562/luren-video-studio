"""Project-level narration rate (语速), nullable for old rows (inherit global)."""
import sqlalchemy as sa
from alembic import op

revision = "0007_project_tts_rate"
down_revision = "0006_transcription_jobs"
branch_labels = None
depends_on = None


def upgrade():
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("video_projects")}
    if "tts_rate" not in existing:
        op.add_column("video_projects", sa.Column("tts_rate", sa.Integer(), nullable=True))


def downgrade():
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("video_projects")}
    if "tts_rate" in existing:
        with op.batch_alter_table("video_projects") as batch:
            batch.drop_column("tts_rate")
