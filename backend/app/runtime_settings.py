"""可在「设置」页运行时覆盖的少量参数，持久化到 `data/runtime_settings.json`。

与 `.env` 的区别：这些参数允许在 UI 里直接改、立即生效且无需重启；只放少量白名单键，
避免把整套环境配置暴露成可写。渲染站点读的是 `get_settings()` 上的同名属性。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .tts_providers import normalize_rate

# 白名单：键 -> 转换/校验函数（返回规范化后的值）。只允许这里列出的键被覆盖。
RUNTIME_KEYS: dict[str, Callable[[object], object]] = {
    "render_concurrency": int,
    "tts_rate": normalize_rate,  # 全局默认语速，存规范字符串（如 "+20%"）
}


def overrides_path(data_dir: Path) -> Path:
    return Path(data_dir) / "runtime_settings.json"


def load_overrides(data_dir: Path) -> dict:
    """读取已持久化的覆盖值；文件缺失/损坏/类型不符时静默回退到空。"""
    path = overrides_path(data_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict = {}
    for key, value in data.items():
        caster = RUNTIME_KEYS.get(key)
        if caster is None or value is None:
            continue
        try:
            result[key] = caster(value)
        except (TypeError, ValueError):
            continue
    return result


def save_overrides(data_dir: Path, values: dict) -> dict:
    """合并写入覆盖值并返回完整集合。"""
    current = load_overrides(data_dir)
    for key, value in values.items():
        caster = RUNTIME_KEYS.get(key)
        if caster is None or value is None:
            continue
        try:
            current[key] = caster(value)
        except (TypeError, ValueError):
            continue
    path = overrides_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current
