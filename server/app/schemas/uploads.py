from pydantic import BaseModel, ConfigDict, HttpUrl


class UploadFromUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
