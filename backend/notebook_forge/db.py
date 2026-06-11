"""Engine/session management + FTS5 search index.

SQLite in WAL mode. The FTS5 virtual table indexes each document's extracted
plain text and is kept in sync by the service layer on every save.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from .config import bootstrap_workspace, db_path
from .models import Base


def make_engine(workspace: Path | None = None) -> Engine:
    ws = bootstrap_workspace(workspace)
    engine = create_engine(f"sqlite:///{db_path(ws)}", json_serializer=_json_dumps)

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text("CREATE VIRTUAL TABLE IF NOT EXISTS doc_fts USING fts5(slug, title, body)")
        )
    return engine


def _json_dumps(obj) -> str:  # noqa: ANN001
    import json

    return json.dumps(obj, ensure_ascii=False, sort_keys=False)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def fts_replace(session: Session, doc_id: int, slug: str, title: str, body: str) -> None:
    """Replace the FTS row for a document (delete + insert keyed on rowid)."""
    session.execute(text("DELETE FROM doc_fts WHERE rowid = :rid").bindparams(rid=doc_id))
    session.execute(
        text("INSERT INTO doc_fts(rowid, slug, title, body) VALUES(:rid, :slug, :title, :body)")
        .bindparams(rid=doc_id, slug=slug, title=title, body=body)
    )


def fts_search(session: Session, query: str, limit: int = 20) -> list[dict]:
    # Quote each term so user input (hyphens, apostrophes…) is never parsed
    # as FTS5 query syntax; terms are implicitly ANDed.
    query = " ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in query.split())
    rows = session.execute(
        text(
            "SELECT rowid, slug, title, snippet(doc_fts, 2, '<b>', '</b>', '…', 12) AS snip "
            "FROM doc_fts WHERE doc_fts MATCH :q ORDER BY rank LIMIT :lim"
        ).bindparams(q=query, lim=limit)
    ).mappings()
    return [dict(r) for r in rows]
