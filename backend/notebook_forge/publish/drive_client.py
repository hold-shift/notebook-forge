"""Real Google Drive client (Drive v3) behind the DriveClient protocol.

Auth: OAuth installed-app flow with the narrow `drive.file` scope (the app
can only see files it created). The refresh token lives in the OS keychain
(`notebook-forge` / `drive-oauth-token`) per the locked secrets decision —
never on disk. The client-secrets JSON path comes from target config; its
contents are read at auth time only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..secrets_store import KEYRING_SERVICE

DRIVE_TOKEN_NAME = "drive-oauth-token"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _load_credentials():  # noqa: ANN202
    import keyring
    from google.oauth2.credentials import Credentials

    raw = keyring.get_password(KEYRING_SERVICE, DRIVE_TOKEN_NAME)
    if not raw:
        return None
    creds = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request

        creds.refresh(Request())
        _save_credentials(creds)
    return creds if creds.valid else None


def _save_credentials(creds) -> None:  # noqa: ANN001
    import keyring

    keyring.set_password(KEYRING_SERVICE, DRIVE_TOKEN_NAME, creds.to_json())


def run_consent_flow(client_secrets_path: Path):  # noqa: ANN202
    """One-time interactive browser consent; caches the token in the
    keychain. Returns valid credentials."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path), SCOPES)
    creds = flow.run_local_server(port=0)
    _save_credentials(creds)
    return creds


def have_credentials() -> bool:
    try:
        return _load_credentials() is not None
    except Exception:
        return False


class GoogleDriveClient:
    """Implements the DriveClient protocol over googleapiclient."""

    def __init__(self) -> None:
        creds = _load_credentials()
        if creds is None:
            raise PermissionError(
                "Drive is not authenticated: run "
                "`python -m notebook_forge.cli drive-auth --secrets <client_secrets.json>` once"
            )
        from googleapiclient.discovery import build

        self._creds = creds
        self.service = build("drive", "v3", credentials=creds, cache_discovery=False)
        self._docs = None  # Docs API, built lazily for tab renaming

    def find_file(self, name: str, folder_id: str) -> str | None:
        safe_name = name.replace("'", "\\'")
        result = (
            self.service.files()
            .list(
                q=f"name = '{safe_name}' and '{folder_id}' in parents and trashed = false",
                fields="files(id)",
                pageSize=1,
            )
            .execute()
        )
        files = result.get("files", [])
        return files[0]["id"] if files else None

    def _media(self, media: bytes, media_mime: str):  # noqa: ANN202
        from googleapiclient.http import MediaInMemoryUpload

        return MediaInMemoryUpload(media, mimetype=media_mime, resumable=True)

    def create_file(self, body: dict[str, Any], media: bytes, media_mime: str) -> str:
        created = (
            self.service.files()
            .create(body=body, media_body=self._media(media, media_mime), fields="id")
            .execute()
        )
        return created["id"]

    def update_file(self, file_id: str, body: dict[str, Any], media: bytes, media_mime: str) -> str:
        updated = (
            self.service.files()
            .update(
                fileId=file_id,
                body=body,
                media_body=self._media(media, media_mime),
                fields="id",
            )
            .execute()
        )
        return updated["id"]

    def set_tab_title(self, file_id: str, title: str) -> None:
        """Rename the document's (single) tab via the Docs API. The Docs API
        accepts the same `drive.file` scope for app-created docs, so no extra
        consent is needed. No-op if the doc somehow exposes no tab."""
        if self._docs is None:
            from googleapiclient.discovery import build

            self._docs = build("docs", "v1", credentials=self._creds, cache_discovery=False)
        doc = (
            self._docs.documents()
            .get(documentId=file_id, includeTabsContent=True, fields="tabs.tabProperties.tabId")
            .execute()
        )
        tabs = doc.get("tabs", [])
        if not tabs:
            return
        tab_id = tabs[0]["tabProperties"]["tabId"]
        self._docs.documents().batchUpdate(
            documentId=file_id,
            body={
                "requests": [
                    {
                        "updateDocumentTabProperties": {
                            "tabProperties": {"tabId": tab_id, "title": title},
                            "fields": "title",
                        }
                    }
                ]
            },
        ).execute()

    def file_link(self, file_id: str) -> str:
        return f"https://docs.google.com/document/d/{file_id}/edit"
