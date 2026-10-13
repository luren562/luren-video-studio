"""运维：按保留期清理可再生产物（引擎工程 / 成片 / 导出 / TTS 缓存）。

用法（backend 目录）：
    .\\.venv\\Scripts\\python.exe -m scripts.cleanup [--days 14] [--dry-run]
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

from app.ops_service import cleanup  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None, help="保留天数（默认取 CLEANUP_RETENTION_DAYS）")
    ap.add_argument("--dry-run", action="store_true", help="只列出不删除")
    args = ap.parse_args()
    result = cleanup(retention_days=args.days, dry_run=args.dry_run)
    for path in result["removed"]:
        print(f"  删除 {path}")
    print(f"共 {result['count']} 项，释放 {result['bytes_freed']} 字节（保留 {result['retention_days']} 天，dry_run={result['dry_run']}）")


if __name__ == "__main__":
    main()
