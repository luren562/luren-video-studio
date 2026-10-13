"""运维：打印系统巡检（DB / 磁盘 / 工具链 / 引擎接入 / 队列 / ASR）。

用法（backend 目录）：
    .\\.venv\\Scripts\\python.exe -m scripts.health
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ops_service import system_health  # noqa: E402


def main() -> None:
    print(json.dumps(system_health(), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
