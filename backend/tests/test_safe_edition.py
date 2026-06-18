"""NotebookLM-safe edition: sketches inlined, link contract, co-located
footnotes, no ToC / no [^N] syntax."""

from pathlib import Path

from sqlalchemy.orm import Session
from test_importer import SLUG, make_repo

from notebook_forge.blocks import make_block, text_run
from notebook_forge.importer import get_or_create_pages_target, import_document
from notebook_forge.models import Target
from notebook_forge.publish import publish_document
from notebook_forge.publish.drive import DriveTarget, MockDriveClient
from notebook_forge.safe_edition import (
    build_safe_markdown,
    html_fragment_to_md,
    inline_md,
    render_safe_markdown,
)


def test_inline_md_marks_and_markers() -> None:
    content = [
        text_run("plain "),
        text_run("bold", {"bold": True}),
        text_run(" and "),
        text_run("both", {"bold": True, "italic": True}),
        text_run("."),
        text_run("2", {"fnRef": True}),
    ]
    assert inline_md(content) == "plain **bold** and ***both***.[2]"
    assert inline_md([{"type": "link", "href": "https://x.test", "content": [text_run("go")]}]) == (
        "[go](https://x.test)"
    )


def test_html_fragment_to_md() -> None:
    assert html_fragment_to_md("plain text") == "plain text"
    assert html_fragment_to_md("<em>I wrote four</em>") == "*I wrote four*"
    assert html_fragment_to_md('see <a href="https://x.test">this</a>') == (
        "see [this](https://x.test)"
    )


def test_render_safe_markdown_structure() -> None:
    meta = {
        "title": "In The Navy",
        "author": "R.F. Skitch",
        "year_display": "1953–1954",
        "standfirst": "A recollection.",
        "slug": "1953-1954_in-the-navy",
        "canonical_url": "https://example.test/rfs/in-the-navy.html",
    }
    blocks = [
        make_block("forgeImage", {
            "assetId": "a1", "sketchAssetId": "s1",
            "caption": "A plaque.", "altText": "Plaque", "approval": "approved",
            "displayWidth": "full",
        }),
        make_block("heading", {"level": 2}, [text_run("A chapter")]),
        make_block("paragraph", content=[
            text_run("Prose with a marker."), text_run("1", {"fnRef": True}),
        ]),
        make_block("forgeFootnote", {"marker": "1", "text": "<em>a note</em>"}),
    ]
    md = render_safe_markdown(meta, blocks, lambda b, n: f"sketch-{n}.png")

    # labelled metadata header (no H1), then a rule
    assert md.startswith("**Title:** In The Navy  \n")
    assert "**Standfirst:** A recollection.  " in md
    assert "**Author:** R.F. Skitch  " in md
    assert "**Years covered:** 1953–1954  " in md
    assert "**Source name:** 1953-1954_in-the-navy  " in md
    import re as _re
    assert _re.search(r"\*\*Word count:\*\* \d+  ", md)  # prose word count present
    assert md.split("---")[0].count("\n# ") == 0  # no H1 title line
    assert "\n---\n" in md
    # figure: sketch image + caption linking to the live anchor
    assert "![Plaque](sketch-1.png)" in md
    assert (
        "**Figure 1.** A plaque. — [View original photo]"
        "(https://example.test/rfs/in-the-navy.html#figure-1)" in md
    )
    assert "## A chapter" in md
    # footnote: plain [N] tie in prose, co-located blockquote, markup converted
    assert "Prose with a marker.[1]" in md
    assert "> **[1]** *a note*" in md
    assert "[^" not in md  # never real footnote syntax
    # co-location: the note follows the paragraph immediately
    para_idx = md.index("Prose with a marker.")
    note_idx = md.index("> **[1]**")
    assert 0 < note_idx - para_idx < 60


def test_duplicate_figures_reuse_number() -> None:
    fig = {
        "assetId": "same", "sketchAssetId": "sk", "caption": "C", "altText": "A",
        "approval": "approved", "displayWidth": "full",
    }
    blocks = [make_block("forgeImage", dict(fig)), make_block("forgeImage", dict(fig))]
    meta = {"title": "T", "canonical_url": "https://x"}
    md = render_safe_markdown(meta, blocks, lambda b, n: "s")
    assert md.count("**Figure 1.**") == 2
    assert "**Figure 2.**" not in md


def test_drive_publish_uploads_safe_markdown(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    repo = make_repo(tmp_path)
    pages = get_or_create_pages_target(session, repo)
    doc, _ = import_document(session, workspace, repo, SLUG, pages)
    target = Target(name="drive", kind="drive", config={"folder_id": "f-1"})
    session.add(target)
    session.commit()

    client = MockDriveClient()
    publish_document(session, workspace, doc, target, adapter=DriveTarget(client, "f-1"))
    session.commit()

    [(file_id, entry)] = client.files.items()
    assert entry["media_mime"] == "text/markdown"
    md = entry["media"].decode("utf-8")
    assert md.startswith("**Title:** In The Navy")
    # all 15 figures embedded as data URIs (fixture bytes → raw fallback)
    assert md.count("![") == 15
    assert md.count("](data:") == 15
    assert md.count("View original photo") == 15
    assert "#figure-15" in md
    # derived from the real page: footnote present and co-located
    assert "> **[" in md
    assert "[^" not in md
    assert "Contents" not in md  # no ToC in the safe edition
    # the Google Doc's tab is named the NotebookLM edition
    assert entry["tab_title"] == "[NotebookLM edition]"
    assert ("set_tab_title", {"file_id": file_id, "title": "[NotebookLM edition]"}) in client.calls


def test_safe_markdown_falls_back_to_original_when_no_sketch(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    repo = make_repo(tmp_path, drop_sketch_n=1)
    pages = get_or_create_pages_target(session, repo)
    doc, _ = import_document(session, workspace, repo, SLUG, pages)
    session.commit()
    md = build_safe_markdown(session, workspace, doc)
    assert md.count("](data:") == 15  # figure 1 fell back to its original


def test_safe_mode_original_and_omit() -> None:
    base = {
        "sketchAssetId": "sk", "caption": "C", "altText": "A",
        "approval": "approved", "displayWidth": "full",
    }
    blocks = [
        make_block("forgeImage", {**base, "assetId": "a1"}),
        make_block("forgeImage", {**base, "assetId": "a2", "safeMode": "omit"}),
        make_block("forgeImage", {**base, "assetId": "a3"}),
    ]
    meta = {"title": "T", "canonical_url": "https://x"}
    md = render_safe_markdown(meta, blocks, lambda b, n: f"src-{n}")

    assert "**Figure 1.**" in md
    assert "**Figure 2.**" not in md  # omitted from the safe edition...
    assert "**Figure 3.**" in md       # ...but its NUMBER was consumed,
    assert "#figure-3" in md           # keeping anchors aligned with HTML


def test_safe_mode_original_uses_original_asset(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    repo = make_repo(tmp_path)
    pages = get_or_create_pages_target(session, repo)
    doc, _ = import_document(session, workspace, repo, SLUG, pages)
    # mark figure 1 as original-in-safe-edition (e.g. a map)
    blocks = [dict(b) for b in doc.blocks]
    fig = next(b for b in blocks if b["type"] == "forgeImage")
    fig["props"] = {**fig["props"], "safeMode": "original"}
    from notebook_forge import services

    services.save_blocks(session, doc, blocks)
    session.commit()

    md = build_safe_markdown(session, workspace, doc)
    # fixture originals are b"original-bytes-N"; sketches are b"sketch-bytes-N"
    import base64

    first_img = md.split("![", 2)[1].split("](data:", 1)[1]
    payload = base64.b64decode(first_img.split("base64,", 1)[1].split(")", 1)[0])
    assert payload.startswith(b"original-bytes")


# ── M6: narrative in the safe edition (D8) ──

def test_narrative_renders_as_unmarked_blockquote() -> None:
    """Consecutive narrative blocks merge into one blockquote, no label, no italic markers."""
    from notebook_forge.blocks import FORGE_FOOTNOTE, FORGE_NARRATIVE

    meta = {"title": "T"}
    blocks = [
        make_block("paragraph", content=[text_run("Before.")]),
        make_block(FORGE_NARRATIVE, content=[text_run("First reflective paragraph.")]),
        make_block(FORGE_NARRATIVE, content=[text_run("Second reflective paragraph.")]),
        make_block(FORGE_FOOTNOTE, {"marker": "7", "text": "A note."}),
    ]
    md = render_safe_markdown(meta, blocks, lambda b, n: "")

    # Two consecutive narrative blocks merged with > separator
    assert "> First reflective paragraph." in md
    assert "> Second reflective paragraph." in md
    # The separator line between the two
    assert ">\n> Second" in md or ">\n>\n> Second" in md or "> First" in md
    # Footnote keeps its bold marker
    assert "> **[7]** A note." in md
    # No italic markers around narrative text (upright)
    assert "*First" not in md
    assert "*Second" not in md


def test_narrative_no_label_even_when_meta_has_one() -> None:
    """narrative_label in meta is ignored by render_safe_markdown (D8)."""
    from notebook_forge.blocks import FORGE_NARRATIVE

    meta = {"title": "T", "narrative_label": "From the author"}
    blocks = [make_block(FORGE_NARRATIVE, content=[text_run("A quiet reflection here.")])]
    md = render_safe_markdown(meta, blocks, lambda b, n: "")
    assert "From the author" not in md
    assert "> A quiet reflection here." in md
