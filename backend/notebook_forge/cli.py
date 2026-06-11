"""Non-interactive CLI. `uv run python -m notebook_forge.cli import-published …`"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import bootstrap_workspace, workspace_path
from .db import make_engine, make_session_factory
from .importer import SIMILARITY_GATE, import_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="notebook-forge")
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import-published", help="import the published memoirs")
    imp.add_argument("--repo", required=True, type=Path, help="family-history clone root")
    imp.add_argument("--mf-out", type=Path, default=None, help="MemoirForge out/ dir")
    imp.add_argument("--mf-work", type=Path, default=None, help="MemoirForge work/ dir")
    imp.add_argument("--reports", type=Path, default=Path("reports"))
    imp.add_argument("--workspace", type=Path, default=None)

    auth = sub.add_parser("drive-auth", help="one-time Drive OAuth consent (opens a browser)")
    auth.add_argument("--secrets", required=True, type=Path, help="OAuth client-secrets JSON")

    args = parser.parse_args(argv)
    if args.command == "drive-auth":
        from .publish.drive_client import run_consent_flow

        creds = run_consent_flow(args.secrets.resolve())
        print("Drive authenticated; token cached in the OS keychain.")
        print("scopes:", " ".join(creds.scopes or []))
        return 0
    if args.command == "import-published":
        ws = bootstrap_workspace(args.workspace or workspace_path())
        engine = make_engine(ws)
        factory = make_session_factory(engine)
        with factory() as session:
            coverages, roundtrips = import_all(
                session,
                ws,
                args.repo.resolve(),
                mf_out=args.mf_out.resolve() if args.mf_out else None,
                mf_work=args.mf_work.resolve() if args.mf_work else None,
                reports_dir=args.reports.resolve(),
            )
            session.commit()
        failed = [r for r in roundtrips if r.similarity < SIMILARITY_GATE]
        for c in coverages:
            print(
                f"{c.slug}: figures={c.figure_blocks} originals={c.originals_found} "
                f"sketches={c.sketches_found} source={'ok' if c.source_found else 'MISSING'}"
            )
        for r in roundtrips:
            print(f"{r.slug}: similarity={r.similarity * 100:.3f}% diffs={len(r.result.diffs)}")
        return 1 if failed else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
