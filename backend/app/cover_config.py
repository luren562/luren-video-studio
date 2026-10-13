"""全局单一 AI 主题封面模型配置（`cover_config` 单例行）。

与生产模型（`ai_models`）完全解耦：封面用哪家生图网关、哪个模型，只在这里配一次。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CoverConfig
from .security import decrypt_string, encrypt_string


def get_row(db: Session) -> CoverConfig:
    """取单例配置行（不存在则建一行空配置）。"""
    row = db.scalar(select(CoverConfig).order_by(CoverConfig.id).limit(1))
    if row is None:
        row = CoverConfig()
        db.add(row)
        db.flush()
    return row


def find_row(db: Session) -> CoverConfig | None:
    return db.scalar(select(CoverConfig).order_by(CoverConfig.id).limit(1))


def is_configured(db: Session) -> bool:
    row = find_row(db)
    return bool(row and row.base_url.strip() and row.model.strip())


def resolved(db: Session) -> dict | None:
    """返回可直接用于生图的配置（api_key 已解密）；未配置返回 None。"""
    row = find_row(db)
    if row is None or not row.base_url.strip() or not row.model.strip():
        return None
    return {
        "base_url": row.base_url.strip(),
        "api_key": decrypt_string(row.encrypted_api_key) if row.encrypted_api_key else "",
        "model": row.model.strip(),
        "size": row.size.strip(),
    }


def to_read(row: CoverConfig) -> dict:
    return {
        "base_url": row.base_url,
        "has_api_key": bool(row.encrypted_api_key),
        "model": row.model,
        "size": row.size,
    }


def save(db: Session, *, base_url: str, model: str, size: str, api_key: str | None) -> CoverConfig:
    row = get_row(db)
    row.base_url = base_url.strip()
    row.model = model.strip()
    row.size = size.strip()
    if api_key is not None and api_key != "":  # 空=保留已存密钥
        row.encrypted_api_key = encrypt_string(api_key)
    return row
