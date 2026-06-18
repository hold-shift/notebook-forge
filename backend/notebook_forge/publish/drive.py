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

# The Google Doc's tab name (square brackets included), so the NotebookLM-safe
# edition is clearly distinguishable from the original.
TAB_TITLE = "[NotebookLM edition]"


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


def csv_request_body(name: str, folder_id: str) -> dict[str, Any]:
    """files.create metadata for a plain text/csv file — NOT converted to a
    Google Sheet, so NotebookLM ingests it as a Data Table."""
    return {"name": name, "mimeType": "text/csv", "parents": [folder_id]}


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

    def set_tab_title(self, file_id: str, title: str) -> None:
        """Rename the Google Doc's first tab (Docs API)."""
        ...


def upsert_file(
    client: DriveClient,
    folder_id: str,
    name: str,
    media: bytes,
    media_mime: str,
    *,
    doc_convert: bool,
) -> tuple[str, str]:
    """Create `name` in the folder, or update it in place if it already exists.

    doc_convert=True imports the media as a Google Doc (the per-doc report);
    doc_convert=False stores it verbatim as a CSV file (the master tracks).
    Returns (file_id, "created"|"updated").
    """
    existing = client.find_file(name, folder_id)
    if existing:
        return (
            client.update_file(existing, update_request_body(name), media, media_mime),
            "updated",
        )
    body = (
        create_request_body(name, folder_id)
        if doc_convert
        else csv_request_body(name, folder_id)
    )
    return client.create_file(body, media, media_mime), "created"


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

    def set_tab_title(self, file_id: str, title: str) -> None:
        self.files[file_id]["tab_title"] = title
        self.calls.append(("set_tab_title", {"file_id": file_id, "title": title}))


class DriveTarget(PublishTarget):
    kind = "drive"

    def __init__(self, client: DriveClient, folder_id: str) -> None:
        self.client = client
        self.folder_id = folder_id

    def publish(self, bundle: PublishBundle) -> PublishResult:
        # The Drive deliverable is the NotebookLM-safe Markdown (sketches
        # inlined, captions linking to the live anchors); Drive converts
        # text/markdown to a Google Doc on import. HTML is the fallback if
        # the caller didn't build a safe edition.
        if bundle.safe_md:
            media, mime = bundle.safe_md.encode("utf-8"), "text/markdown"
        else:
            media, mime = bundle.html.encode("utf-8"), "text/html"
        existing = self.client.find_file(bundle.slug, self.folder_id)
        if existing:
            file_id = self.client.update_file(
                existing, update_request_body(bundle.slug), media, mime
            )
            action = "updated"
        else:
            file_id = self.client.create_file(
                create_request_body(bundle.slug, self.folder_id), media, mime
            )
            action = "created"
        # Name the document's tab so it's clearly the NotebookLM edition.
        # Best-effort: a tab failure must not fail an otherwise-good publish.
        tab_set = False
        if mime == "text/markdown":
            try:
                self.client.set_tab_title(file_id, TAB_TITLE)
                tab_set = True
            except Exception:  # noqa: BLE001 — Docs API is non-critical
                tab_set = False
        return PublishResult(
            ok=True,
            detail={
                "file_id": file_id, "action": action,
                "media_mime": mime, "tab_titled": tab_set,
            },
        )
