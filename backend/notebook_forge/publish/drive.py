"""DriveTarget — interface, request shapes and a mocked client (M6 scope).

Real OAuth + uploads are next sprint. The request shapes follow the Drive
v3 API (files.create / files.update with multipart media), matching the
MemoirForge M2 publish flow: the document is uploaded for conversion to a
Google Doc; re-publishing updates the existing Doc so its URL is stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .base import PublishBundle, PublishResult, PublishTarget


def create_request_body(name: str, folder_id: str) -> dict[str, Any]:
    """files.create metadata: import-convert to a Google Doc."""
    return {
        "name": name,
        "mimeType": "application/vnd.google-apps.document",
        "parents": [folder_id],
    }


def update_request_body(name: str) -> dict[str, Any]:
    """files.update metadata (no parents on update; folder is unchanged)."""
    return {"name": name}


class DriveClient(Protocol):
    """The thin slice of the Drive v3 client the target needs. The real
    implementation (next sprint) wraps google-api-python-client; tests use
    MockDriveClient."""

    def find_file(self, name: str, folder_id: str) -> str | None:
        """Return the file id of `name` within the folder, or None."""
        ...

    def create_file(self, body: dict[str, Any], media: bytes, media_mime: str) -> str:
        """files.create with multipart media → new file id."""
        ...

    def update_file(self, file_id: str, body: dict[str, Any], media: bytes, media_mime: str) -> str:
        """files.update with new media → same file id."""
        ...


@dataclass
class MockDriveClient:
    """Records request shapes; simulates stable file ids across updates."""

    files: dict[str, dict[str, Any]] = field(default_factory=dict)  # id -> {body, media}
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    _next_id: int = 1

    def find_file(self, name: str, folder_id: str) -> str | None:
        self.calls.append(("find", {"name": name, "folder_id": folder_id}))
        for file_id, entry in self.files.items():
            if entry["body"].get("name") == name and folder_id in entry["body"].get(
                "parents", [folder_id]
            ):
                return file_id
        return None

    def create_file(self, body: dict[str, Any], media: bytes, media_mime: str) -> str:
        file_id = f"mock-file-{self._next_id}"
        self._next_id += 1
        self.files[file_id] = {"body": body, "media": media, "media_mime": media_mime}
        self.calls.append(("create", {"body": body, "media_mime": media_mime}))
        return file_id

    def update_file(self, file_id: str, body: dict[str, Any], media: bytes, media_mime: str) -> str:
        self.files[file_id] = {
            "body": {**self.files[file_id]["body"], **body},
            "media": media,
            "media_mime": media_mime,
        }
        self.calls.append(("update", {"file_id": file_id, "body": body}))
        return file_id


class DriveTarget(PublishTarget):
    kind = "drive"

    def __init__(self, client: DriveClient, folder_id: str) -> None:
        self.client = client
        self.folder_id = folder_id

    def publish(self, bundle: PublishBundle) -> PublishResult:
        # Next sprint the media will be the NotebookLM-safe edition (sketches
        # inlined). Tonight the shape is exercised with the rendered HTML.
        media = bundle.html.encode("utf-8")
        existing = self.client.find_file(bundle.slug, self.folder_id)
        if existing:
            file_id = self.client.update_file(
                existing, update_request_body(bundle.slug), media, "text/html"
            )
            action = "updated"
        else:
            file_id = self.client.create_file(
                create_request_body(bundle.slug, self.folder_id), media, "text/html"
            )
            action = "created"
        return PublishResult(ok=True, detail={"file_id": file_id, "action": action})
