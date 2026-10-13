"""运维（批次 F）单测：health / backup / cleanup。"""

import os
import time
import zipfile

from app.config import Settings
from app.ops_service import backup, cleanup, restore, system_health


def test_system_health_shape():
    health = system_health()
    assert health["status"] in ("ok", "degraded")
    assert {"db", "disk", "tools", "engines", "counts"} <= set(health)


def test_backup_then_cleanup(tmp_path):
    db = tmp_path / "x.db"
    db.write_text("db")
    assets = tmp_path / "assets"
    (assets / "tts_cache").mkdir(parents=True)
    (assets / "tts_cache" / "old.wav").write_text("x")
    renders = tmp_path / "renders"
    renders.mkdir()
    (renders / "old.mp4").write_text("x")
    (tmp_path / "engine_runtime" / "shotcraft" / "projects" / "p1").mkdir(parents=True)
    (tmp_path / "engine_runtime" / "shotcraft" / "projects" / "p1" / "f.txt").write_text("x")

    settings = Settings(
        data_dir=tmp_path, assets_dir=assets, uploads_dir=tmp_path / "uploads",
        renders_dir=renders, backup_dir=tmp_path / "backups",
        database_url=f"sqlite:///{(db).as_posix()}",
    )

    out = backup(settings)
    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert "backend.db" in names
    assert any(n.startswith("data/assets/") for n in names)

    # 把可再生产物的 mtime 调到过去，retention=0 应清理
    old = time.time() - 100000
    for p in [renders / "old.mp4", assets / "tts_cache" / "old.wav",
              tmp_path / "engine_runtime" / "shotcraft" / "projects" / "p1"]:
        os.utime(p, (old, old))
    result = cleanup(settings, retention_days=0)
    assert result["count"] >= 3
    assert not (renders / "old.mp4").exists()
    assert not (tmp_path / "engine_runtime" / "shotcraft" / "projects" / "p1").exists()


def test_backup_restore_roundtrip(tmp_path):
    data = tmp_path / "data"
    assets = data / "assets"
    assets.mkdir(parents=True)
    (assets / "a.txt").write_text("x", encoding="utf-8")
    (data / "backend.db").write_text("db", encoding="utf-8")
    settings = Settings(
        data_dir=data, assets_dir=assets, uploads_dir=data / "uploads",
        renders_dir=data / "renders", backup_dir=tmp_path / "backups",
        database_url=f"sqlite:///{(data / 'backend.db').as_posix()}",
    )
    out = backup(settings)
    dest = tmp_path / "restore"
    result = restore(out, settings, dest_dir=dest)
    assert (dest / "assets" / "a.txt").read_text(encoding="utf-8") == "x"
    assert (dest / "backend.db").exists()
    assert result["entries"] >= 2


def test_cleanup_dry_run_keeps_files(tmp_path):
    renders = tmp_path / "renders"
    renders.mkdir()
    f = renders / "keep.mp4"
    f.write_text("x")
    os.utime(f, (time.time() - 100000, time.time() - 100000))
    settings = Settings(
        data_dir=tmp_path, assets_dir=tmp_path / "assets", uploads_dir=tmp_path / "uploads",
        renders_dir=renders, backup_dir=tmp_path / "backups", database_url="sqlite:///:memory:",
    )
    result = cleanup(settings, retention_days=0, dry_run=True)
    assert result["dry_run"] is True and f.exists()
