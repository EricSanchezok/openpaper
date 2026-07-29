"""Identity commands independent of HTTP and persistence."""

from pydantic import BaseModel, ConfigDict


class SetUserBlockedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocked: bool
