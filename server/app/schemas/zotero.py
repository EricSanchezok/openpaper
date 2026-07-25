from datetime import datetime

from pydantic import BaseModel, Field


class ZoteroConnectResponse(BaseModel):
    auth_url: str


class ZoteroStatusResponse(BaseModel):
    connected: bool
    connected_at: datetime | None = None
    last_synced_at: datetime | None = None


class ZoteroDisconnectResponse(BaseModel):
    success: bool
    message: str


class ZoteroImportRequest(BaseModel):
    item_keys: list[str] = Field(..., min_length=1, max_length=50)


class ZoteroImportItemResult(BaseModel):
    zotero_item_key: str
    paper_id: str | None = None
    upload_job_id: str | None = None
    import_source: str | None = None
    title: str | None = None


class ZoteroImportError(BaseModel):
    zotero_item_key: str
    error: str


class ZoteroImportResponse(BaseModel):
    imported: list[ZoteroImportItemResult]
    imported_count: int
    imported_via_url: int
    skipped_already_imported: int
    errors: list[ZoteroImportError]


class ZoteroImportStatusItem(BaseModel):
    zotero_item_key: str
    paper_id: str | None = None
    upload_job_id: str | None = None
    import_source: str
    status: str
    title: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    last_synced_at: datetime | None = None


class ZoteroImportStatusListResponse(BaseModel):
    items: list[ZoteroImportStatusItem]


class ZoteroSyncResponse(BaseModel):
    synced_papers_count: int
    new_annotations_count: int


class ZoteroLibraryItem(BaseModel):
    zotero_item_key: str
    title: str
    authors: list[str]
    date: str | None = None
    item_type: str
    venue: str | None = None
    date_added: str | None = None
    tags: list[str] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)
    already_imported: bool
    has_pdf_attachment: bool = False
    has_metadata: bool = True


class ZoteroLibraryResponse(BaseModel):
    items: list[ZoteroLibraryItem]
    remaining_slots: int
