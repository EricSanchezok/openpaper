"""Shared, explicit return boundary for FastAPI handlers."""

from pydantic import BaseModel
from starlette.responses import Response

ApiResponse = Response
ApiData = BaseModel | dict[str, object] | list[object] | None
