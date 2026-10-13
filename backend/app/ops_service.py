"""运维（批次 F）：health 巡检、备份/恢复、磁盘清理。

- `system_health`：DB / 磁盘 / 工具链 / 引擎接入 / 队列计数 / ASR 可用性。
- `backup`：把 DB 与关键数据目录打成带时间戳的 zip。
- `cleanup`：按保留天数清理引擎工程、成片、导出、TTS 缓存等可再生产物。
"""

from __future__ import annotations

import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from sqlalchemy import func, select, text

from .config import Settings, get_settings
from .database import SessionLocal
from .toolchain import ensure_tool_paths

ENGINE_DIRS = ("video-shotcraft",)


def _tree_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                continue
    return total


def _counts() -> dict:
    from .models import PipelineTask, RenderOutput, VideoProject

    with SessionLocal() as session:
        session.execute(text("SELECT 1"))

        def c(model, *where) -> int:
            stmt = select(func.count()).select_from(model)
            for cond in where:
                stmt = stmt.where(cond)
            return session.scalar(stmt) or 0

        return {
            "projects_total": c(VideoProject),
            "outputs_total": c(RenderOutput),
            "tasks_queued": c(PipelineTask, PipelineTask.status == "queued"),
            "tasks_running": c(PipelineTask, PipelineTask.status == "running"),
            "tasks_failed": c(PipelineTask, PipelineTask.status == "failed"),
        }


def system_health(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    tools = ensure_tool_paths()
    db_ok = True
    counts: dict = {}
    error = ""
    try:
        counts = _counts()
    except Exception as exc:  # noqa: BLE001
        db_ok = False
        error = str(exc)

    try:
        usage = shutil.disk_usage(str(settings.data_dir))
        disk = {"total": usage.total, "used": usage.used, "free": usage.free,
                "percent": round(usage.used / usage.total * 100, 1) if usage.total else 0.0}
    except OSError:
        disk = {"total": 0, "used": 0, "free": 0, "percent": 0.0}

    engines = {name: (settings.engines_dir / name).exists() for name in ENGINE_DIRS}

    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "error": error,
        "disk": disk,
        "tools": tools,
        "engines": engines,
        "counts": counts,
    }


def backup(settings: Settings | None = None, dest_dir: Path | None = None, include_renders: bool = False) -> Path:
    """把 DB + assets/uploads/exports（可选 renders）打 zip；返回 zip 路径。"""
    settings = settings or get_settings()
    dest_dir = dest_dir or settings.backup_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = dest_dir / f"backup_{stamp}.zip"

    roots: list[tuple[Path, str]] = []
    if settings.is_sqlite:
        db_path = Path(settings.database_url.removeprefix("sqlite:///"))
        if db_path.exists():
            roots.append((db_path, "backend.db"))
    roots.append((settings.assets_dir, "data/assets"))
    roots.append((settings.uploads_dir, "data/uploads"))
    roots.append((settings.data_dir / "exports", "data/exports"))
    if include_renders:
        roots.append((settings.renders_dir, "data/renders"))

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, arc in roots:
            if not root.exists():
                continue
            if root.is_file():
                zf.write(root, arc)
                continue
            for path in root.rglob("*"):
                if path.is_file():
                    zf.write(path, f"{arc}/{path.relative_to(root).as_posix()}")
    logger.info(f"备份完成：{out}（{out.stat().st_size} 字节）")
    return out


def cleanup(settings: Settings | None = None, retention_days: int | None = None, dry_run: bool = False) -> dict:
    """清理超过保留期的可再生产物（引擎工程 / 成片 / 导出 / TTS 缓存）。"""
    settings = settings or get_settings()
    days = retention_days if retention_days is not None else settings.cleanup_retention_days
    cutoff = time.time() - days * 86400
    targets: list[Path] = []

    runtime_projects = settings.data_dir / "engine_runtime"
    for proj in runtime_projects.glob("*/projects/*"):
        if proj.is_dir():
            targets.append(proj)
    targets.extend(p for p in settings.renders_dir.glob("*") if p.is_file())
    targets.extend(p for p in (settings.data_dir / "exports").glob("*"))
    targets.extend(p for p in (settings.assets_dir / "tts_cache").glob("*"))

    removed: list[str] = []
    freed = 0
    for path in targets:
        try:
            if path.stat().st_mtime >= cutoff:
                continue
            size = _tree_size(path)
            if not dry_run:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
            removed.append(str(path))
            freed += size
        except OSError as exc:
            logger.warning(f"清理失败 {path}：{exc}")
    logger.info(f"清理{'（演练）' if dry_run else ''}：{len(removed)} 项，释放 {freed} 字节（保留 {days} 天）")
    return {"removed": removed, "count": len(removed), "bytes_freed": freed,
            "retention_days": days, "dry_run": dry_run}


def restore(zip_path: Path, settings: Settings | None = None, dest_dir: Path | None = None) -> dict:
    """把备份 zip 解回 dest_dir（默认 data_dir）；不自动覆盖正在运行的 DB。

    `backup()` 的归档结构是：DB 在根下 `backend.db`，数据目录在 `data/<name>/`。
    这里把 `data/` 前缀剥掉后落到 dest_dir（默认 data_dir），使 `restore(backup(...))`
    能回到原位；已存在的 `backend.db` 不覆盖（保护运行中的库）。
    """
    settings = settings or get_settings()
    target = dest_dir or settings.data_dir
    target.mkdir(parents=True, exist_ok=True)
    entries = 0
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            entries += 1
            if member.endswith("/"):
                continue
            rel = member[len("data/"):] if member.startswith("data/") else member
            out = target / rel
            if out.exists() and out.name == "backend.db":
                logger.warning(f"跳过已存在的 DB（不覆盖运行中的库）：{out}")
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    return {"restored_to": str(target), "entries": entries}
