"""Project accent, music and Chinese narration preferences (nullable for old rows)."""
import sqlalchemy as sa
from alembic import op

revision = "0003_project_audio_theme"
down_revision = "0002_review_required"
branch_labels = None
depends_on = None


def upgrade():
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("video_projects")}
    for name, type_ in [("theme_json", sa.JSON()), ("bgm_enabled", sa.Boolean()),
                        ("tts_enabled", sa.Boolean()), ("tts_voice", sa.String(120)),
                        ("tts_asset_id", sa.Integer())]:
        if name not in existing:
            op.add_column("video_projects", sa.Column(name, type_, nullable=True))


def downgrade():
    with op.batch_alter_table("video_projects") as batch:
        for name in ("tts_asset_id", "tts_voice", "tts_enabled", "bgm_enabled", "theme_json"):
            batch.drop_column(name)
