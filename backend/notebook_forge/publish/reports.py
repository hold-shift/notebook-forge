"""Push analytical reports to Drive — same folder/auth as the safe editions.

Two deliverables, both into the configured drive target's folder:
- Per-doc report: a Google Doc named `report_<source_name>` (Markdown imported
  and converted, mirroring the safe edition), tracked on the Report row so a
  re-push updates the same Doc in place.
- Master tracks: four Google Sheets (`master_people`, …) — the CSV media is
  imported and converted to Sheets so NotebookLM can sync them as Data Tables.

The drive client + folder come from `make_adapter` on the drive Target, so the
mock/real selection, OAuth, and "no folder configured" errors are shared with
the publish flow. A `client`/`folder_id` pair can be injected for tests.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import services
from ..models import Document, Target, utcnow
from .drive import GOOGLE_DOC_MIME, GOOGLE_SHEET_MIME, DriveClient, upsert_file

# The report Doc's tab name, distinguishing it from the "[NotebookLM edition]".
REPORT_TAB_TITLE = "[Analytical report]"


def _drive_client_and_folder(
    session: Session, workspace: Path
) -> tuple[DriveClient, str]:
    """Resolve the drive target's client + folder via the publish adapter."""
    from .service import make_adapter

    target = session.scalar(select(Target).where(Target.kind == "drive"))
    if target is None:
        raise PermissionError("no Drive target is configured")
    adapter = make_adapter(target, workspace)  # DriveTarget; raises if unauthenticated
    return adapter.client, adapter.folder_id


def push_report(
    session: Session,
    workspace: Path,
    doc: Document,
    *,
    client: DriveClient | None = None,
    folder_id: str | None = None,
) -> dict[str, Any]:
    """Push the document's report as `report_<source_name>` to Drive.

    Raises PermissionError (→ 409) if the report has not been generated yet or
    no Drive target is configured.
    """
    from ..reports.service import get_report

    report = get_report(session, doc)
    if report is None:
        raise PermissionError("generate the report before pushing it to Drive")
    if client is None or folder_id is None:
        client, folder_id = _drive_client_and_folder(session, workspace)

    name = f"report_{report.source_name}"
    file_id, action = upsert_file(
        client, folder_id, name, report.body_md.encode("utf-8"), "text/markdown",
        drive_mime=GOOGLE_DOC_MIME,
    )
    # Best-effort tab rename — a Docs API hiccup must not fail a good push.
    try:
        client.set_tab_title(file_id, REPORT_TAB_TITLE)
    except Exception:  # noqa: BLE001
        pass

    report.drive_file_id = file_id
    report.pushed_at = utcnow()
    services.record_change(
        session, doc, "publish", f"pushed report to Drive ({action})",
        detail={"file_id": file_id, "action": action, "name": name, "kind": "report"},
    )
    return {"file_id": file_id, "action": action, "name": name}


def push_master(
    session: Session,
    workspace: Path,
    *,
    client: DriveClient | None = None,
    folder_id: str | None = None,
) -> dict[str, dict[str, str]]:
    """Build the four master tracks and upload each as a Google Sheet (CSV
    media converted on import). Returns per-track {file_id, action, name}."""
    from ..reports.master import MASTER_SHEET_NAMES, build_master_csvs

    if client is None or folder_id is None:
        client, folder_id = _drive_client_and_folder(session, workspace)

    results: dict[str, dict[str, str]] = {}
    for track_type, text in build_master_csvs(session).items():
        name = MASTER_SHEET_NAMES[track_type]
        file_id, action = upsert_file(
            client, folder_id, name, text.encode("utf-8"), "text/csv",
            drive_mime=GOOGLE_SHEET_MIME,
        )
        results[track_type] = {"file_id": file_id, "action": action, "name": name}
    return results
