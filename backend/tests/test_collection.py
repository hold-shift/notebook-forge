"""Collection-index publishing: derived catalogue, nav, root artefacts."""

from pathlib import Path

from sqlalchemy.orm import Session
from test_importer import SLUG, make_repo

from notebook_forge.blocks import make_block, text_run
from notebook_forge.collection import (
    count_words,
    nav_for,
    reading_time,
    root_files,
)
from notebook_forge.importer import get_or_create_pages_target, import_document
from notebook_forge.models import Target
from notebook_forge.publish import publish_document


def test_reading_time_formats() -> None:
    assert reading_time(0) == ""
    assert reading_time(1000) == "~5 min read"  # 5 min floor
    assert reading_time(5000) == "~25 min read"
    assert reading_time(28903) == "~2½ hr read"  # junior's live value
    assert reading_time(24200) == "~2 hr read"


def test_count_words_excludes_figures_and_footnotes() -> None:
    blocks = [
        make_block("paragraph", content=[text_run("one two three")]),
        make_block("heading", {"level": 2}, [text_run("four five")]),
        make_block("forgeImage", {"caption": "not counted at all"}),
        make_block("forgeFootnote", {"marker": "1", "text": "also not counted"}),
    ]
    assert count_words(blocks) == 5


def test_count_words_footnote_marker_is_a_token() -> None:
    # matches the live counting rule: tags become spaces, so the marker
    # digit separates from the word it abuts
    blocks = [
        make_block(
            "paragraph",
            content=[text_run("as well."), text_run("1", {"fnRef": True}), text_run(" and on")],
        )
    ]
    assert count_words(blocks) == 5  # as / well. / 1 / and / on


def _import_two(tmp_path: Path, workspace: Path, session: Session):
    import shutil

    repo = make_repo(tmp_path)
    rfs = repo / "rfs"
    second = "1971-1980_later-years"
    html = (rfs / f"{SLUG}.html").read_text().replace("In The Navy", "Later Years")
    (rfs / f"{second}.html").write_text(html)
    shutil.copytree(rfs / f"{SLUG}_assets", rfs / f"{second}_assets")
    target = get_or_create_pages_target(session, repo)
    d1, _ = import_document(session, workspace, repo, SLUG, target)
    d2, _ = import_document(session, workspace, repo, second, target)
    session.commit()
    return d1, d2, target


def test_nav_is_derived_from_chronological_order(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    d1, d2, _ = _import_two(tmp_path, workspace, session)
    prev1, next1 = nav_for(session, d1)
    assert prev1 is None
    assert next1 and next1["title"] == "Later Years"
    prev2, next2 = nav_for(session, d2)
    assert prev2 and prev2["title"] == "In The Navy"
    assert next2 is None

    # a title edit propagates into the neighbour's nav immediately
    d2.meta = {**d2.meta, "title": "The Later Years"}
    session.flush()
    _, next1 = nav_for(session, d1)
    assert next1["title"] == "The Later Years"


def test_root_files_regenerate_on_publish(
    tmp_path: Path, workspace: Path, session: Session
) -> None:
    d1, d2, _ = _import_two(tmp_path, workspace, session)
    out = tmp_path / "site"
    local = Target(name="local", kind="local-folder", config={"folder": str(out)})
    session.add(local)
    session.commit()

    publish_document(session, workspace, d1, local)
    session.commit()
    for name in ("index.html", "catalogue.json", "sitemap.xml", "robots.txt", "llms.txt"):
        assert (out / name).exists(), name

    index = (out / "index.html").read_text()
    assert "In The Navy" in index and "Later Years" in index
    catalogue = (out / "catalogue.json").read_text()
    assert '"stem": "1971-1980_later-years"' in catalogue
    llms = (out / "llms.txt").read_text()
    assert "## Documents" in llms and "Later Years" in llms
    sitemap = (out / "sitemap.xml").read_text()
    assert sitemap.count("<url>") == 3  # homepage + 2 docs
    assert "Sitemap:" in (out / "robots.txt").read_text()

    # docnav in the published page uses DERIVED neighbours
    html = (out / f"{SLUG}.html").read_text()
    assert 'class="nm">Later Years' in html


def test_root_files_shape(tmp_path: Path, workspace: Path, session: Session) -> None:
    _import_two(tmp_path, workspace, session)
    files = root_files(session, base_url="https://example.org/archive")
    assert set(files) == {"index.html", "catalogue.json", "sitemap.xml", "robots.txt", "llms.txt"}
    assert '"rebuilt"' in files["catalogue.json"]
    assert "https://example.org/archive/sitemap.xml" in files["robots.txt"]
    assert 'application/ld+json' in files["index.html"]
    assert '"@type":"CreativeWorkSeries"' in files["index.html"]
