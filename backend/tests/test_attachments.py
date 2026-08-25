"""forgeAttachment: hosted PDFs/documents linked from a page.

Covers the whole chain — naming helpers, page render, HTML round-trip,
search text, publish bundle, safe edition, JSON-LD and the upload route.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_importer import SLUG, make_repo

from notebook_forge.blocks import (
    FORGE_ATTACHMENT,
    attachment_published_path,
    ext_label,
    format_bytes,
    make_block,
    plain_text,
    text_run,
)
from notebook_forge.models import Target
from notebook_forge.parser import parse_article
from notebook_forge.publish import publish_document
from notebook_forge.renderer import render_document

PDF_BYTES = b"%PDF-1.4\n% a tiny but real-enough pdf\n%%EOF\n"


def attachment_block(
    *,
    asset_id: str = "sha-1",
    name: str = "Annex C — Order of battle",
    description: str = "Sub-unit listing for the task force, March 1968.",
    filename: str = "annex-c.pdf",
    mime: str = "application/pdf",
    size: int = 2_517_621,
    path: str = "",
) -> dict:
    return make_block(
        FORGE_ATTACHMENT,
        {
            "assetId": asset_id,
            "name": name,
            "description": description,
            "filename": filename,
            "mime": mime,
            "sizeBytes": size,
            "path": path,
        },
    )


# ── naming + label helpers ───────────────────────────────────────────────────

def test_published_path_defaults_to_the_site_root() -> None:
    assert (
        attachment_published_path("Annex A — Operation Order 1/66", "scan final v2.PDF")
        == "annex-a-operation-order-1-66.pdf"
    )


def test_published_path_honours_an_operator_folder() -> None:
    assert (
        attachment_published_path(
            "Annex A — Operation Order 1/66", "scan.pdf", "rfs/vietnam/attachments"
        )
        == "rfs/vietnam/attachments/annex-a-operation-order-1-66.pdf"
    )
    # Leading and trailing slashes are noise, not meaning.
    assert attachment_published_path("Annex A", "scan.pdf", "/rfs/vietnam/") == (
        "rfs/vietnam/annex-a.pdf"
    )


def test_published_path_accepts_a_full_path_with_filename() -> None:
    assert (
        attachment_published_path("Annex A", "scan.pdf", "rfs/vietnam/oporder-1-66.pdf")
        == "rfs/vietnam/oporder-1-66.pdf"
    )


def test_published_path_forces_the_real_extension() -> None:
    """A typed path can rename the file but never re-label its type."""
    assert attachment_published_path("Annex A", "scan.pdf", "rfs/evil.html") == (
        "rfs/evil.pdf"
    )


def test_published_path_cannot_escape_the_site_root() -> None:
    assert attachment_published_path("Annex A", "scan.pdf", "../../etc/passwd") == (
        "etc/passwd/annex-a.pdf"
    )
    assert attachment_published_path("Annex A", "scan.pdf", "rfs/../x") == (
        "rfs/x/annex-a.pdf"
    )


def test_published_path_falls_back_to_the_filename() -> None:
    assert attachment_published_path("", "Signals Instruction.docx") == (
        "signals-instruction.docx"
    )
    assert attachment_published_path("", "") == "attachment"


def test_ext_and_size_labels() -> None:
    assert ext_label("annex-c.pdf", "application/pdf") == "PDF"
    assert ext_label("noext", "application/pdf") == "PDF"
    assert ext_label("", "") == "FILE"
    assert format_bytes(0) == ""
    assert format_bytes(900) == "900 bytes"
    assert format_bytes(2_517_621) == "2.4 MB"
    assert format_bytes(52_428_800) == "50 MB"


# ── page render ──────────────────────────────────────────────────────────────

def render_one(block: dict) -> BeautifulSoup:
    html = render_document(
        {"title": "T", "show_toc": False},
        [block],
        lambda b, n: "",
        lambda b, n: f"doc_assets/attachment-{n}-annex-c.pdf",
    )
    return BeautifulSoup(html, "lxml")


def test_render_attachment_card() -> None:
    soup = render_one(attachment_block())
    a = soup.find("a", class_="attachment")
    assert a is not None
    assert a["href"] == "doc_assets/attachment-1-annex-c.pdf"
    assert a["id"] == "attachment-1"
    assert a["target"] == "_blank"
    assert "noopener" in a["rel"]
    assert a.find("span", class_="att-name").get_text() == "Annex C — Order of battle"
    assert "Sub-unit listing" in a.find("span", class_="att-desc").get_text()
    assert a.find("span", class_="att-ext").get_text() == "PDF"
    meta = a.find("span", class_="att-meta").get_text()
    assert "PDF" in meta and "2.4 MB" in meta and "opens in a new tab" in meta


def test_render_attachment_numbers_in_document_order() -> None:
    blocks = [
        attachment_block(name="Annex A", filename="a.pdf"),
        make_block("paragraph", content=[text_run("Between them.")]),
        attachment_block(name="Annex B", filename="b.docx", mime="x/docx", size=310_000),
    ]
    html = render_document(
        {"title": "T", "show_toc": False},
        blocks,
        lambda b, n: "",
        lambda b, n: f"doc_assets/attachment-{n}.bin",
    )
    soup = BeautifulSoup(html, "lxml")
    ids = [a["id"] for a in soup.find_all("a", class_="attachment")]
    assert ids == ["attachment-1", "attachment-2"]
    assert soup.find_all("a", class_="attachment")[1].find(
        "span", class_="att-ext"
    ).get_text() == "DOCX"


def test_render_attachment_without_description() -> None:
    soup = render_one(attachment_block(description=""))
    a = soup.find("a", class_="attachment")
    assert a.find("span", class_="att-desc") is None
    assert a.find("span", class_="att-name") is not None


# ── HTML round-trip (the re-import / idempotency gate) ───────────────────────

def test_attachment_html_round_trips() -> None:
    def src(_b: dict, n: int) -> str:
        return f"doc_assets/attachment-{n}-annex-c.pdf"

    blocks = [attachment_block()]
    html1 = render_document({"title": "T", "show_toc": False}, blocks, lambda b, n: "", src)
    parsed, _images = parse_article(BeautifulSoup(html1, "lxml").find("article"))

    assert len(parsed) == 1
    props = parsed[0]["props"]
    assert parsed[0]["type"] == FORGE_ATTACHMENT
    assert props["name"] == "Annex C — Order of battle"
    assert props["description"] == "Sub-unit listing for the task force, March 1968."
    assert props["mime"] == "application/pdf"
    assert props["sizeBytes"] == 2_517_621
    assert props["filename"] == "attachment-1-annex-c.pdf"
    assert props["path"] == ""

    html2 = render_document({"title": "T", "show_toc": False}, parsed, lambda b, n: "", src)
    assert html1 == html2


# ── search index ─────────────────────────────────────────────────────────────

def test_plain_text_indexes_name_and_description() -> None:
    text = plain_text([attachment_block()])
    assert "Annex C — Order of battle" in text
    assert "Sub-unit listing for the task force, March 1968." in text


# ── narration + reports ──────────────────────────────────────────────────────

def test_attachment_is_not_narrated() -> None:
    from notebook_forge.narration import extract_blocks

    exported = extract_blocks(
        [
            make_block("paragraph", content=[text_run("Spoken prose.")]),
            attachment_block(),
        ]
    )
    assert [b["text"] for b in exported] == ["Spoken prose."]


def test_attachment_reaches_the_report_chunker() -> None:
    from notebook_forge.reports.chunker import chunk_document

    chunks = chunk_document([attachment_block()])
    assert "[Attachment: Annex C — Order of battle — Sub-unit listing" in chunks[0].text


# ── publish ──────────────────────────────────────────────────────────────────

def doc_with_attachment(tmp_path: Path, workspace: Path, session: Session, path: str = ""):
    from notebook_forge import services
    from notebook_forge.assets import ingest_file
    from notebook_forge.importer import get_or_create_pages_target, import_document

    repo = make_repo(tmp_path)
    pages = get_or_create_pages_target(session, repo)
    doc, _ = import_document(session, workspace, repo, SLUG, pages)

    src = tmp_path / "annex-c.pdf"
    src.write_bytes(PDF_BYTES)
    asset = ingest_file(session, workspace, src, "attachments")
    session.commit()

    blocks = doc.blocks + [
        attachment_block(asset_id=asset.sha256, size=len(PDF_BYTES), path=path)
    ]
    services.save_blocks(session, doc, blocks, summary="attach annex C")
    session.commit()
    return doc


def test_publish_puts_an_unpathed_attachment_at_the_site_root(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    doc = doc_with_attachment(tmp_path, workspace, session)
    out = tmp_path / "site"
    target = Target(name="local", kind="local-folder", config={"folder": str(out)})
    session.add(target)
    session.commit()

    publish_document(session, workspace, doc, target)
    session.commit()

    published = out / "annex-c-order-of-battle.pdf"
    assert published.exists()
    assert published.read_bytes() == PDF_BYTES
    html = (out / f"{SLUG}.html").read_text()
    assert (
        'href="https://chris-skitch.github.io/family-history/'
        'annex-c-order-of-battle.pdf"' in html
    )


def test_publish_honours_an_operator_path(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    doc = doc_with_attachment(
        tmp_path, workspace, session, path="rfs/vietnam/attachments"
    )
    out = tmp_path / "site"
    target = Target(name="local", kind="local-folder", config={"folder": str(out)})
    session.add(target)
    session.commit()

    publish_document(session, workspace, doc, target)
    session.commit()

    published = out / "rfs" / "vietnam" / "attachments" / "annex-c-order-of-battle.pdf"
    assert published.exists()
    assert published.read_bytes() == PDF_BYTES
    html = (out / f"{SLUG}.html").read_text()
    assert (
        'href="https://chris-skitch.github.io/family-history/rfs/vietnam/attachments/'
        'annex-c-order-of-battle.pdf"' in html
    )
    # The page also carries the operator's raw path, so a re-import restores it.
    assert 'data-path="rfs/vietnam/attachments"' in html


def test_publish_pushes_the_file_to_a_git_pages_target(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    """The path is relative to the SITE root, not the pages subdir — so an
    attachment can sit beside (or above) the rendered pages."""
    import subprocess

    from notebook_forge.publish import GitPagesTarget

    bare = tmp_path / "pages.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True
    )
    doc = doc_with_attachment(tmp_path, workspace, session, path="vietnam/attachments")
    target = Target(
        name="pages",
        kind="github-pages",
        config={"push_url": str(bare), "branch": "main", "subdir": "rfs"},
    )
    session.add(target)
    session.commit()

    adapter = GitPagesTarget(
        push_url=str(bare), clones_dir=tmp_path / "clones", branch="main", subdir="rfs"
    )
    publish_document(session, workspace, doc, target, adapter=adapter)
    session.commit()

    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "main"],
        cwd=bare, capture_output=True, text=True, check=True,
    ).stdout.split()
    assert "vietnam/attachments/annex-c-order-of-battle.pdf" in listing
    assert f"rfs/{SLUG}.html" in listing


def test_publish_refuses_two_attachments_on_one_path(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    from notebook_forge import services

    doc = doc_with_attachment(tmp_path, workspace, session)
    blocks = doc.blocks + [
        attachment_block(asset_id=doc.blocks[-1]["props"]["assetId"], filename="other.pdf")
    ]
    services.save_blocks(session, doc, blocks, summary="duplicate")
    session.commit()

    out = tmp_path / "site"
    target = Target(name="local", kind="local-folder", config={"folder": str(out)})
    session.add(target)
    session.commit()

    with pytest.raises(PermissionError, match="would both publish to"):
        publish_document(session, workspace, doc, target)


def test_publish_refuses_a_path_another_document_owns(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    from notebook_forge import services
    from notebook_forge.services import create_document

    doc = doc_with_attachment(tmp_path, workspace, session)
    other = create_document(session, "1968-other", "Other memoir")
    services.save_blocks(
        session,
        other,
        [attachment_block(asset_id=doc.blocks[-1]["props"]["assetId"])],
        summary="same path",
    )
    session.commit()

    out = tmp_path / "site"
    target = Target(name="local", kind="local-folder", config={"folder": str(out)})
    session.add(target)
    session.commit()

    with pytest.raises(PermissionError, match="already used by the document"):
        publish_document(session, workspace, doc, target)


def test_publish_refuses_to_overwrite_a_site_root_file(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    doc = doc_with_attachment(tmp_path, workspace, session, path="robots.txt")
    out = tmp_path / "site"
    target = Target(name="local", kind="local-folder", config={"folder": str(out)})
    session.add(target)
    session.commit()

    # Same stem, and .txt is an allowed upload type — so this is reachable.
    doc.blocks[-1]["props"]["filename"] = "robots.txt"
    session.commit()
    with pytest.raises(PermissionError, match="site's own files"):
        publish_document(session, workspace, doc, target)


def test_safe_edition_links_out_to_the_hosted_copy(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    from notebook_forge.safe_edition import build_safe_markdown

    doc = doc_with_attachment(
        tmp_path, workspace, session, path="rfs/vietnam/attachments"
    )
    doc.meta = {
        **doc.meta,
        "canonical_url": "https://chris-skitch.github.io/family-history/rfs/junior.html",
        "slug": SLUG,
    }
    session.commit()

    md = build_safe_markdown(session, workspace, doc)
    assert (
        "**Attachment 1.** [Annex C — Order of battle]"
        "(https://chris-skitch.github.io/family-history/rfs/vietnam/attachments/"
        "annex-c-order-of-battle.pdf) — PDF" in md
    )
    assert "Sub-unit listing for the task force, March 1968." in md
    # A PDF is never inlined as a data URI (Drive's conversion ceiling).
    assert "data:application/pdf" not in md


# ── JSON-LD ──────────────────────────────────────────────────────────────────

def test_jsonld_graph_carries_each_attachment(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    import json

    from notebook_forge.structured_data import article_graph, build_context

    doc = doc_with_attachment(
        tmp_path, workspace, session, path="rfs/vietnam/attachments"
    )
    ctx = build_context(session, doc, base_url="https://history.skitch.me")
    graph = article_graph(ctx)
    nodes = [n for n in graph["@graph"] if "DigitalDocument" in (n.get("@type") or [])]

    assert len(nodes) == 1
    node = nodes[0]
    assert node["name"] == "Annex C — Order of battle"
    assert node["contentUrl"] == (
        "https://history.skitch.me/rfs/vietnam/attachments/annex-c-order-of-battle.pdf"
    )
    assert node["encodingFormat"] == "application/pdf"
    assert node["contentSize"] == format_bytes(len(PDF_BYTES))

    article = next(n for n in graph["@graph"] if n.get("@type") == "Article")
    assert article["hasPart"] == [{"@id": node["@id"]}]
    json.dumps(graph)  # serialisable


def test_jsonld_omits_haspart_without_attachments(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    from notebook_forge.importer import get_or_create_pages_target, import_document
    from notebook_forge.structured_data import article_graph, build_context

    repo = make_repo(tmp_path)
    pages = get_or_create_pages_target(session, repo)
    doc, _ = import_document(session, workspace, repo, SLUG, pages)
    session.commit()

    graph = article_graph(build_context(session, doc, base_url="https://history.skitch.me"))
    article = next(n for n in graph["@graph"] if n.get("@type") == "Article")
    assert "hasPart" not in article


# ── upload route ─────────────────────────────────────────────────────────────

@pytest.fixture()
def client(workspace: Path):
    import os

    os.environ["NOTEBOOK_FORGE_WORKSPACE"] = str(workspace)
    from notebook_forge.api import _state, app

    _state.cache_clear()
    with TestClient(app) as c:
        yield c


def make_doc(client: TestClient) -> str:
    r = client.post("/api/documents", json={"title": "Annex A to M"})
    assert r.status_code == 200
    return r.json()["slug"]


def test_upload_attachment_returns_display_metadata(client: TestClient) -> None:
    slug = make_doc(client)
    r = client.post(
        f"/api/documents/{slug}/attachments/upload",
        files={"file": ("Annex C.pdf", PDF_BYTES, "application/pdf")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filename"] == "Annex C.pdf"
    assert body["mime"] == "application/pdf"
    assert body["sizeBytes"] == len(PDF_BYTES)
    assert body["warning"] == ""
    assert len(body["assetId"]) == 64


def test_upload_attachment_rejects_disallowed_type(client: TestClient) -> None:
    slug = make_doc(client)
    r = client.post(
        f"/api/documents/{slug}/attachments/upload",
        files={"file": ("payload.exe", b"MZ", "application/octet-stream")},
    )
    assert r.status_code == 415
    assert ".pdf" in r.json()["detail"]


def test_upload_attachment_rejects_oversize_file(client: TestClient, monkeypatch) -> None:
    from notebook_forge import api

    monkeypatch.setattr(api, "MAX_ATTACHMENT_BYTES", 10)
    slug = make_doc(client)
    r = client.post(
        f"/api/documents/{slug}/attachments/upload",
        files={"file": ("big.pdf", b"x" * 64, "application/pdf")},
    )
    assert r.status_code == 413


def test_attachment_path_round_trips() -> None:
    """The operator's raw path survives a re-import — it can't be re-derived
    from the absolute href, which already has the site base folded in."""
    def src(_b: dict, _n: int) -> str:
        return "https://history.skitch.me/rfs/vietnam/attachments/annex-c.pdf"

    blocks = [attachment_block(path="rfs/vietnam/attachments")]
    html1 = render_document({"title": "T", "show_toc": False}, blocks, lambda b, n: "", src)
    parsed, _images = parse_article(BeautifulSoup(html1, "lxml").find("article"))

    assert parsed[0]["props"]["path"] == "rfs/vietnam/attachments"
    html2 = render_document({"title": "T", "show_toc": False}, parsed, lambda b, n: "", src)
    assert html1 == html2
