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

    nm = sub.add_parser(
        "narrative-migrate",
        help="migrate full-italic paragraphs to forgeNarrative blocks",
    )
    nm_mode = nm.add_mutually_exclusive_group(required=True)
    nm_mode.add_argument("--dry-run", action="store_true", help="scan only; no DB writes")
    nm_mode.add_argument("--apply", action="store_true", help="snapshot + convert affected docs")
    nm.add_argument("--force", action="store_true", help="re-apply even if already applied")
    nm.add_argument("--workspace", type=Path, default=None)
    nm.add_argument("--reports", type=Path, default=Path("reports"))

    ri = sub.add_parser(
        "reimport",
        help="re-import docs from archived MemoirForge sources, reusing existing sketches",
    )
    ri.add_argument(
        "slugs", nargs="*",
        help="document slug(s) to re-import (omit when --all is set)",
    )
    ri.add_argument(
        "--all", action="store_true",
        help="re-import every library doc with a matching MemoirForge manifest",
    )
    ri.add_argument(
        "--dry-run", action="store_true",
        help="extract + hash-match only; no DB or workspace writes",
    )
    ri.add_argument(
        "--reports", type=Path, default=Path("reports"),
        help="directory to write reimport-dryrun.md (default: reports/)",
    )
    ri.add_argument("--workspace", type=Path, default=None)

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

    if args.command == "narrative-migrate":
        return _cmd_narrative_migrate(args)

    if args.command == "reimport":
        return _cmd_reimport(args)

    return 2


def _cmd_narrative_migrate(args: argparse.Namespace) -> int:
    from .narrative_migration import already_applied, apply, scan, write_report

    ws = bootstrap_workspace(args.workspace or workspace_path())
    engine = make_engine(ws)
    factory = make_session_factory(engine)

    with factory() as session:
        if args.apply and not args.force:
            marker = already_applied(session)
            if marker is not None:
                applied_at = marker.get("applied_at", "unknown")
                print(
                    f"ERROR: migration already applied at {applied_at}. "
                    "Use --force to re-apply.",
                    file=sys.stderr,
                )
                return 1

        rows = scan(session)
        affected = [r for r in rows if r["count"] > 0]
        print(
            f"Scanned {len(rows)} document(s); "
            f"{len(affected)} affected; "
            f"{sum(r['count'] for r in rows)} conversion(s) total."
        )
        for row in rows:
            if row["count"] == 0:
                continue
            flagged = sum(1 for c in row["conversions"] if c.get("flagged"))
            print(
                f"  {row['slug']}: {row['count']} conversion(s)"
                + (f", {flagged} flagged" if flagged else "")
            )

        mode = "dry-run" if args.dry_run else "apply"
        write_report(args.reports.resolve(), rows, mode)
        print(f"\nReport written to {args.reports.resolve() / 'narrative_migration.md'}")

        if args.apply:
            apply(session)
            session.commit()
            print(f"Applied: {len(affected)} document(s) converted.")

    return 0


def _cmd_reimport(args: argparse.Namespace) -> int:
    from .reimport import (
        EXCLUDED_STEMS,
        dry_run,
        find_manifest_for_doc,
        list_manifest_slugs,
        reimport_document,
    )

    # Validate slug list.
    for slug in args.slugs:
        if slug in EXCLUDED_STEMS:
            print(
                f"ERROR: '{slug}' is the national-service test run — never re-import it.",
                file=sys.stderr,
            )
            return 1

    if args.dry_run:
        slugs = list_manifest_slugs() if args.all else args.slugs
        if not slugs:
            print("ERROR: specify slug(s) or --all", file=sys.stderr)
            return 1

        reports: list[dict] = []
        any_error = False
        for slug in slugs:
            try:
                report = dry_run(slug)
            except LookupError as exc:
                print(f"  {slug}: SKIP — {exc}")
                any_error = True
                continue
            matched = report["matched"]
            total = report["figures_extracted"]
            pct = f"{matched * 100 // total}%" if total else "n/a"
            missing = len(report.get("missing_silhouettes", []))
            print(
                f"  {slug}: {report['match_rate']} matched ({pct})"
                + (f" | {missing} silhouette(s) missing" if missing else "")
                + (f" | {len(report['unmatched'])} unmatched" if report["unmatched"] else "")
            )
            if report.get("error"):
                print(f"    ERROR: {report['error']}")
                any_error = True
            reports.append(report)

        _write_dryrun_report(args.reports.resolve(), reports)
        return 1 if any_error else 0

    # Real re-import.
    ws = bootstrap_workspace(args.workspace or workspace_path())
    engine = make_engine(ws)
    factory = make_session_factory(engine)

    from . import services

    with factory() as session:
        if args.all:
            docs = services.list_documents(session)
        else:
            if not args.slugs:
                print("ERROR: specify slug(s) or --all", file=sys.stderr)
                return 1
            docs = []
            for slug in args.slugs:
                doc = services.get_document(session, slug)
                if doc is None:
                    # Slug may be a manifest stem rather than the library slug
                    # (e.g. 1934-1945_junior vs the ingested 1930-1945_junior).
                    # Try to resolve via the manifest's source_file.
                    try:
                        from .reimport import find_memoir_manifest
                        mf = find_memoir_manifest(slug)
                        all_docs = services.list_documents(session)
                        doc = next(
                            (d for d in all_docs
                             if d.meta.get("source_file") == mf.source_file),
                            None,
                        )
                    except LookupError:
                        pass
                if doc is None:
                    print(f"  {slug}: SKIP — not found in library")
                else:
                    docs.append(doc)

        any_error = False
        for doc in docs:
            try:
                manifest = find_manifest_for_doc(doc)
                result = reimport_document(session, ws, doc, manifest=manifest)
                session.commit()
                print(
                    f"  {doc.slug}: text_blocks={result['text_blocks']} "
                    f"figures={result['figures']} "
                    f"carried_over={result['figures_carried_over_by_assetid']} "
                    f"seeded={result['seeded']} "
                    f"cache_seeded={result['cache_seeded']}"
                    + (f" unmatched={len(result['unmatched'])}" if result["unmatched"] else "")
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  {doc.slug}: ERROR — {exc}")
                any_error = True

    return 1 if any_error else 0


def _write_dryrun_report(reports_dir: Path, reports: list[dict]) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / "reimport-dryrun.md"

    lines = [
        "# Re-import dry-run — hash match rates",
        "",
        "Generated by `notebook-forge reimport --all --dry-run`.",
        "Excludes the national-service test run (`1942-1954_national-service`).",
        "",
        "| Document | Source | Extracted | In manifest | Matched | Match rate |",
        "|---|---|---|---|---|---|",
    ]
    for r in reports:
        if r.get("error"):
            lines.append(
                f"| {r['slug']} | {r.get('source_file', '?')} | — | — | — | ERROR: {r['error']} |"
            )
        else:
            total = r["figures_extracted"]
            pct = f"{r['matched'] * 100 // total}%" if total else "n/a"
            lines.append(
                f"| {r['slug']} | {r.get('source_file', '?')} "
                f"| {total} | {r['figures_in_manifest']} "
                f"| {r['matched']} | {pct} |"
            )

    # Unmatched detail.
    any_unmatched = [r for r in reports if r.get("unmatched")]
    if any_unmatched:
        lines += ["", "## Unmatched figures", ""]
        for r in any_unmatched:
            lines.append(f"### {r['slug']}")
            lines.append("")
            for u in r["unmatched"]:
                err = f" {u['error']}" if u.get("error") else ""
                lines.append(
                    f"- order={u.get('order', '?')} sha256={u.get('sha256', '?')}{err}"
                )
            lines.append("")

    # Missing silhouette detail.
    any_missing = [r for r in reports if r.get("missing_silhouettes")]
    if any_missing:
        lines += ["", "## Missing silhouette files", ""]
        for r in any_missing:
            lines.append(f"### {r['slug']}")
            lines.append("")
            for m in r["missing_silhouettes"]:
                lines.append(f"- fig {m['n']} ({m['anchor']}): `{m.get('expected_path', '?')}`")
            lines.append("")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nDry-run report written to {out}")


if __name__ == "__main__":
    sys.exit(main())
