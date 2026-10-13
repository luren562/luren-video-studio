from sqlalchemy import String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .config import get_settings
from .database import Base
from .security import hash_password


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))


def ensure_default_admin(session: Session) -> None:
    settings = get_settings()
    existing = session.scalar(select(AdminUser).where(AdminUser.username == settings.admin_username))
    if existing is None:
        session.add(
            AdminUser(
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
            )
        )
        session.commit()
