"""运维：备份 DB + 关键数据目录为带时间戳的 zip。

用法（backend 目录）：
    .\\.venv\\Scripts\\python.exe -m scripts.backup [--include-renders]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ops_service import backup  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-renders", action="store_true", help="连同成片目录一起备份（体积大）")
    args = ap.parse_args()
    out = backup(include_renders=args.include_renders)
    print(f"备份完成：{out}")


if __name__ == "__main__":
    main()
