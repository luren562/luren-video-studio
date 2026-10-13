"""引擎共享运行时脚手架（从 shotcraft_compiler 抽取）。

只负责「引擎目录定位 + 依赖安装 + 子进程执行」这类与具体编译路线无关的能力，
供 agent 路径复用；不含配方卡、镜头编排等结构化编译逻辑。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .config import Settings

ENGINE_KEY = "shotcraft"
ENGINE_DIRNAME = "video-shotcraft"
RUNTIME_NAME = "shotcraft"


def runtime_root(settings: Settings, engine=None) -> Path:
    name = getattr(engine, "runtime_name", None) or RUNTIME_NAME
    return settings.data_dir / "engine_runtime" / name


def engine_root(settings: Settings, engine=None) -> Path:
    dirname = getattr(engine, "dir_name", None) or ENGINE_DIRNAME
    return settings.engines_dir / dirname


def _run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, env=env, check=False,
        )
    except subprocess.TimeoutExpired:
        return -1, f"[timeout >{timeout}s]"
    except FileNotFoundError as exc:
        return -1, f"[not found] {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def ensure_runtime(settings: Settings, engine=None) -> Path:
    """确保引擎共享运行时存在（引擎依赖只装一次）。

    - `template`（shotcraft）：把 `runtime_package` 拷进 `runtime_root` 并 `npm install`。
    - `skill-runtime`（talkcraft）：依赖由 skill 自管（`runtime/check-runtime.sh`），
      只在 skill 内准备，不在平台目录安装。
    """
    scaffold = getattr(engine, "scaffold", "template") or "template"
    if scaffold == "skill-runtime":
        repo = engine_root(settings, engine)
        shared = repo / "runtime" / "node_modules"
        if shared.exists():
            return runtime_root(settings, engine)
        script = repo / "runtime" / "check-runtime.sh"
        if not script.exists():
            raise RuntimeError(f"引擎运行时脚本未接入：{script}")
        code, out = _run(["bash", str(script)], repo, 3600)
        if code != 0:
            raise RuntimeError(f"talkcraft 运行时准备失败：{out[-400:]}")
        return runtime_root(settings, engine)
    root = runtime_root(settings, engine)
    if (root / "node_modules").exists():
        return root
    package = getattr(engine, "runtime_package", None) or "template/package.json"
    src_pkg = engine_root(settings, engine) / package
    if not src_pkg.exists():
        raise RuntimeError(f"引擎模板未接入：{src_pkg}")
    root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_pkg, root / "package.json")
    npm = shutil.which("npm") or shutil.which("npm.cmd") or "npm"
    code, out = _run([npm, "install", "--no-audit", "--no-fund"], root, 1800)
    if code != 0:
        raise RuntimeError(f"shotcraft 依赖安装失败：{out[-400:]}")
    return root
