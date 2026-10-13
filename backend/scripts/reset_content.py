"""清空创作内容：项目 / 版本 / 场景 / 成片 / 素材 / 任务记录。

保留：管理员账号、风格档（video_styles）、AI 供应商与模型、内容策略。
默认先备份（ops_service.backup → data/backups/*.zip），再删库记录与可再生产物
（renders / exports / projects / engine_runtime/*/projects / assets 里的 broll·screenshots·icons·tts_cache）。

用法（backend 目录）：
    .\\.venv\\Scripts\\python.exe -m scripts.reset_content --yes [--no-backup] [--keep-assets]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    EngineRun,
    MediaAsset,
    PipelineEvent,
    PipelineTask,
    RenderOutput,
    ReviewDecision,
    VideoProject,
    VideoScene,
    VideoVersion,
)

CONTENT_MODELS = [PipelineEvent, ReviewDecision, RenderOutput, EngineRun, VideoScene, VideoVersion, PipelineTask, VideoProject, MediaAsset]


def _clear_files(settings, keep_assets: bool) -> list[str]:
    removed: list[str] = []
    targets: list[Path] = [settings.renders_dir, settings.data_dir / "exports", settings.data_dir / "projects"]
    runtime = settings.data_dir / "engine_runtime"
    for projects in runtime.glob("*/projects"):
        targets.append(projects)
    if not keep_assets:
        targets += [settings.assets_dir / "broll", settings.assets_dir / "screenshots",
                    settings.assets_dir / "icons", settings.assets_dir / "tts_cache"]
    for target in targets:
        if not target.exists():
            continue
        for child in target.iterdir():
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
                removed.append(str(child))
            except OSError:
                continue
    return removed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="确认执行（否则只报告不删除）")
    ap.add_argument("--no-backup", action="store_true", help="跳过备份")
    ap.add_argument("--keep-assets", action="store_true", help="保留 assets 下的素材文件")
    args = ap.parse_args()

    settings = get_settings()
    with SessionLocal() as session:
        counts = {m.__tablename__: session.query(m).count() for m in CONTENT_MODELS}
    print("将清空：")
    for table, n in counts.items():
        print(f"  {table}: {n}")

    if not args.yes:
        print("未加 --yes，未做任何修改。")
        return

    if not args.no_backup:
        from app.ops_service import backup

        out = backup(settings)
        print(f"已备份：{out}")

    with SessionLocal() as session:
        for model in CONTENT_MODELS:
            session.query(model).delete()
        session.commit()

    removed = _clear_files(settings, keep_assets=args.keep_assets)
    print(f"已删除 {sum(counts.values())} 条记录、{len(removed)} 个产物文件/目录。")


if __name__ == "__main__":
    main()
