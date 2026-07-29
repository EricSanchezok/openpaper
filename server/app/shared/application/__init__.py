"""Framework-independent application contracts."""

from .actor import Actor
from .unit_of_work import UnitOfWork

__all__ = ["Actor", "UnitOfWork"]
