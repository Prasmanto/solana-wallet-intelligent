"""Database base — legacy compatibility layer.

New code should import from app.infrastructure.database.base.
"""

from app.infrastructure.database.base import Base

__all__ = ["Base"]
