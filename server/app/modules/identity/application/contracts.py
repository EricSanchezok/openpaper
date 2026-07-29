"""Identity commands independent of HTTP and persistence."""

from pydantic import BaseModel, ConfigDict


class BlockUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int
    blocked: bool
