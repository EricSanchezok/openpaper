from pydantic import BaseModel, ConfigDict


class ResearchCreatorResponse(BaseModel):
    """Public identity attached to a shared Project research output."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str | None
