from dataclasses import dataclass
@dataclass
class MediaItem:
    url: str
    width: int | None = None
    height: int | None = None
    mime_type: str | None = None
    filename: str | None = None
    captured_at: int | None = None
    uploaded_at: int | None = None
    byte_size: int | None = None
    source_id: str | None = None
