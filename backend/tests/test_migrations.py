"""Alembic 迁移接入（批次 A）单测。"""

from sqlalchemy import inspect

from app.database import Base, engine
from app.migrations import upgrade_database


def test_baseline_applied_and_idempotent():
    # lifespan 已跑过一次；这里再跑应幂等
    upgrade_database()
    names = set(inspect(engine).get_table_names())
    assert "alembic_version" in names
    assert names & set(Base.metadata.tables.keys())
