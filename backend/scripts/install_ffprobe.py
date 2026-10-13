"""开发/部署辅助：把 ffprobe 装到 PATH（与系统 ffmpeg 同目录）。

用法（backend 目录）：
    .\\.venv\\Scripts\\python.exe -m scripts.install_ffprobe
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.toolchain import ensure_tool_paths, install_ffprobe  # noqa: E402


def main() -> None:
    info = install_ffprobe()
    tools = ensure_tool_paths()
    print(f"ffprobe 已安装：{info['ffprobe']}")
    print(f"来源：{info['version_source']}")
    print(f"PATH 解析：ffmpeg={tools['ffmpeg']} ffprobe={tools['ffprobe']}")


if __name__ == "__main__":
    main()
