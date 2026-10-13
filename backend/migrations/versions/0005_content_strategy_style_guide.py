"""content_strategies.style_guide_md (作者风格画像全文)."""
import sqlalchemy as sa
from alembic import op

revision = "0005_content_strategy_style_guide"
down_revision = "0003_project_audio_theme"
branch_labels = None
depends_on = None


def upgrade():
    if "content_strategies" not in sa.inspect(op.get_bind()).get_table_names():
        return
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("content_strategies")}
    if "style_guide_md" not in cols:
        op.add_column(
            "content_strategies",
            sa.Column("style_guide_md", sa.Text(), nullable=False, server_default=""),
        )


def downgrade():
    op.drop_column("content_strategies", "style_guide_md")
