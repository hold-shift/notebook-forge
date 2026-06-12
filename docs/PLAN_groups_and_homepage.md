# Build plan — Document groups + homepage as a first-class document

**Author:** Fable (architect pass, 12 June 2026)
**Executor:** Claude Sonnet, in a later session. Follow this plan literally; every
design decision is made here. Where the plan and the code disagree about a line
number or an identifier, trust the code's current shape but keep the plan's
intent and contracts exactly.

**Baseline:** branch `main` at `18bb48a` (109 backend + 20 frontend tests green
via `make check`). All paths below are repo-relative.

## 0. Current-state screenshots

> **Note:** the two current-state screenshots
> (`docs/screenshots/2026-06-12-library.png` — the Library as shipped — and
> `docs/screenshots/2026-06-12-settings-homepage.png` — the Settings homepage
> section as shipped) were supposed to be copied from
> `~/Desktop/Screenshot 2026-06-12 at 13.26.47.png` and
> `…13.27.27.png`, but those files were **not found** on Desktop, Downloads,
> Pictures, or via Spotlight at planning time. `docs/screenshots/` exists and
> is empty. Executor: do **not** block on this. If the operator re-captures
> them later they land at the paths above; the textual description of the
> current UI in §1 is sufficient to implement against.

## 1. Current state (verified by reading the code)

- **Library** ([frontend/src/views/Library.tsx](../frontend/src/views/Library.tsx)):
  flat list of doc cards ordered by slug (backend orders
  `Document.slug` ascending in `services.list_documents`). Toolbar has a
  search box and one status filter `<select>`. No grouping, no sorting, no
  drag. Top nav: `Library | Settings` + Add document.
- **Settings** ([frontend/src/views/Settings.tsx](../frontend/src/views/Settings.tsx)):
  first section is "Homepage (collection index)" with Site title / Welcome /
  Dedication fields, a "Save homepage" button and one
  "Rebuild index → {target}" button per non-drive target. This entire section
  is removed by this plan.
- **Homepage rendering** ([backend/notebook_forge/collection.py](../backend/notebook_forge/collection.py)
  `root_files()` → [backend/templates/index.html.j2](../backend/templates/index.html.j2)):
  index.html is rendered from the `homepage` Settings row
  (`title`/`welcome`/`dedication`/`footer_html`) plus catalogue entries built
  from all documents in chronological order (`_start_year(slug)`, then slug).
  Root files (`index.html`, `catalogue.json`, `sitemap.xml`, `robots.txt`,
  `llms.txt`) are regenerated on **every** document publish
  ([backend/notebook_forge/publish/service.py](../backend/notebook_forge/publish/service.py)
  `publish_document`) and by the standalone `rebuild_index` /
  `POST /api/rebuild-index/{target}` action.
- **Dirty state** ([backend/notebook_forge/services.py](../backend/notebook_forge/services.py)):
  `is_dirty(session, doc, target)` compares
  `content_hash(doc.blocks, doc.meta)` ([backend/notebook_forge/blocks.py](../backend/notebook_forge/blocks.py),
  SHA-256 of id-stripped blocks + meta, sorted keys) against
  `snapshot.content_hash` recorded in that target's `sync_state` row.
  Snapshots are taken at publish time with the same hash function.
- **Schema** ([backend/notebook_forge/models.py](../backend/notebook_forge/models.py)):
  seven tables; `Base.metadata.create_all` runs on every engine boot
  ([backend/notebook_forge/db.py](../backend/notebook_forge/db.py)). There is
  **no column-migration mechanism** — `create_all` only creates missing
  tables. This plan introduces one (M1).
- **Editor** ([frontend/src/views/Editor.tsx](../frontend/src/views/Editor.tsx)):
  BlockNote editor with `forgeSchema`
  ([frontend/src/forge/schema.tsx](../frontend/src/forge/schema.tsx) — two
  custom blocks `forgeImage`, `forgeFootnote`, `fnRef` style), 1.2 s autosave,
  MetaBar (title/years/standfirst/contents/slug/re-ingest/polish), outline
  sidebar, PendingPanel (per-target dirty + push + unpublish), SnapshotsPanel,
  Delete. Routing is hash-based in
  [frontend/src/App.tsx](../frontend/src/App.tsx)
  (`#/doc/{slug}`, `#/settings`, default library).
- **Known corpus quirk:** the workspace library currently contains a duplicate
  test document titled lowercase "junior · 1930–1945" (created during
  interactive testing of ingest/rename). See §8 cleanup note — nothing in this
  plan deletes it automatically.

## 2. Locked decisions and rationale

These were decided at planning time. Do not revisit them.

| # | Decision | Rationale |
|---|---|---|
| D1 | Lightweight in-repo migration runner (`migrate.py`, PRAGMA-guarded `ALTER TABLE`), no Alembic. | One DB, one user, three columns + one table. Alembic is overhead the project's `create_all` style doesn't want. |
| D2 | `documents` gains `kind` (`'memoir'` default / `'homepage'`) in addition to `group_id`, `group_position`. | The homepage is "a document row of kind='homepage'" per the feature spec; a kind column is the minimal discriminator and keeps the singleton query trivial. |
| D3 | Homepage singleton: `slug='homepage'`, `kind='homepage'`, `title='Homepage'`. | Stable, human-readable, and `_start_year('homepage')` → 9999 is irrelevant because all corpus queries filter `kind=='memoir'` (D10). |
| D4 | Dedication becomes a third custom block `forgeDedication` (props `{text}`, `content: 'none'`), patterned exactly on `forgeFootnote`. | The published `.dedication` style needs a dedicated block; the footnote block proves the props-text + custom-view pattern works in this BlockNote version with zero schema risk. |
| D5 | Dirty mechanism: `effective_content_hash(session, doc)` = plain `content_hash` for memoirs; for the homepage it is `content_hash(blocks, meta ⊕ {"__group_listing__": fingerprint})` where the fingerprint resolves every `forgeDocGroup` block (membership, order, rendered metadata). Snapshots and `is_dirty` both use it. | Reuses the existing hash-vs-snapshot machinery unchanged. Because the hash is computed lazily at read time, *any* library change (reorder, regroup, rename, prose edit affecting word count) makes the homepage dirty automatically — no event wiring, no triggers, no stale flags. |
| D6 | Fingerprint includes only what the block **renders**: group `name`, member order, and per-member `title`, `years`, `standfirst`; `description` only when `showBlurbs`, `word_count` only when `showWordCounts`. Group `color` and member `updated_at` are excluded. | Color is a Library-only affordance (not on the published page); `updated_at` changes on every save and would cause spurious dirty — its *ordering effect* under `last_updated` sort is already captured by member order. |
| D7 | Library drag-and-drop uses **native HTML5 DnD** (`draggable` handles, `onDragOver`/`onDrop`), no new dependency. | The interactions are simple row-reorder and drop-on-header; dnd-kit would add a dependency and abstraction for no functional gain. Deterministic to implement. |
| D8 | Group colors: free `#rrggbb` validated by regex; the UI offers a fixed 8-swatch palette: `#9c5a3c #b08a3e #5a7d5a #5e8c8c #4a6d8c #7d6a8f #8c4a5e #6b6b6b`. | Palette keeps the archive look coherent; regex storage keeps the API future-proof. First swatch is the house accent. |
| D9 | One-time migration creates a single group **"The Memoirs"** (color `#9c5a3c`) containing all memoir docs in chronological order, and the migrated homepage ends with one `forgeDocGroup` block referencing it (`sort='date_range'`, `showBlurbs=true`, `showWordCounts=true`, `layout='list'`). | The migrated homepage must render the same page as today. The current index is exactly "all docs, chronological, with blurbs and word counts" under the hardcoded seclabel "The Memoirs" — naming the group that makes the output byte-identical. |
| D10 | All corpus-derived artefacts (`/api/documents` list, `build_entries`, catalogue, sitemap, llms.txt, JSON-LD `hasPart`, docnav) filter `kind == 'memoir'`. FTS keeps indexing the homepage (harmless; the editor handles its kind). | The homepage must never list itself; machine-readable artefacts stay complete regardless of grouping. |
| D11 | After migration, the homepage lists **only grouped documents**. A newly ingested doc is Ungrouped and does not appear on the published homepage until assigned to a group. `llms.txt`/`sitemap`/`catalogue.json` still include everything. | This is the point of curated groups. The behaviour change from "auto-listed" is deliberate and documented for the operator (§8). |
| D12 | Homepage publishes through the standard push flow; `POST /api/rebuild-index/{target}` and `PUT /api/settings/homepage` endpoints are **removed** (with their `api.ts` clients and Settings UI). The internal `rebuild_index()` function is removed too; homepage publish replaces it. | Two parallel ways to publish the index is exactly the confusion this feature removes. |
| D13 | The homepage cannot be published to `drive` targets; its target rows exclude drive everywhere. It also cannot be deleted, renamed, unpublished, or polished (API returns 409 for each). | Drive holds NotebookLM-safe *documents*, not the site index. The singleton invariants are enforced server-side, not just hidden in the UI. |
| D14 | A regular document publish (which already regenerates root files) also marks the homepage clean for that target **iff** the homepage was dirty — snapshot + `mark_published` in the same transaction. Drive publishes don't. | The pushed commit contains the freshly rendered index, so claiming the homepage is still dirty would be a lie; skipping when already clean avoids snapshot spam. |
| D15 | Migration self-verifies: it renders the homepage via the new block path and via the legacy settings path; if byte-identical, it seeds `PUBLISHED` + snapshot for `github-pages` and `local-folder`; otherwise it leaves `NEVER_PUBLISHED` and records a warning change row. | Honest sync state, in the sprint's round-trip spirit. The live site really is showing this content; seeding clean avoids a phantom "never published" pill — but only when provably equivalent. |
| D16 | `root_files()` returns `(files: dict, warnings: list[str])`. Publish responses carry `warnings`; the frontend alerts when non-empty. | Deleted/empty group blocks must be skipped *visibly* at publish time per the feature spec. |
| D17 | Manual sort is only offered when group-by = Group. In other group-bys the option is disabled (tooltip: "Manual order applies to groups") and the effective sort falls back to Date range. | `group_position` is per-group; pretending a global manual order exists under Status/Format buckets would be false. |
| D18 | Library control state (`groupBy`, `sort`) persists in `localStorage` keys `nf-library-groupby` / `nf-library-sort`. Defaults: `group` / `manual`. | Manual default makes drag handles visible immediately after migration (positions are seeded chronologically, so nothing looks shuffled). |
| D19 | Group membership changes record a per-document change-log row (`kind='edit'`, "moved to group 'X'" / "removed from group"); within-group reorders do **not** (would spam n rows per drag). | History where it's cheap and meaningful; the homepage fingerprint covers reorder dirtiness. |
| D20 | `compact_grid` layout: CSS grid `repeat(auto-fill, minmax(260px, 1fr))`, tighter card padding, description omitted even when `showBlurbs=true`. The card meta row (with "Read →") always renders; word count + reading time appear in it only when `showWordCounts`. | Compact means compact; the arrow is a navigation affordance, not metadata. |
| D21 | `index.html.j2` keeps its legacy variable path behind `{% if body_entries is not defined %}` so the migration equivalence check (D15) can render both ways from one template, guaranteeing identical head/masthead/card markup. The legacy path is removed in a later sprint, not now. | Byte-fidelity between old and new rendering is the migration gate; sharing the template is the only way to guarantee it. |
| D22 | The homepage editor hides MetaBar, outline sidebar, polish, re-ingest, slug, and Delete; it keeps autosave, PendingPanel (non-drive targets), and SnapshotsPanel. The `/group` slash command is registered only when editing the homepage. | The H1 block *is* the title; memoir-specific chrome is noise. `forgeDocGroup` in a memoir would be silently skipped by the page renderer — don't offer it. |
| D23 | Homepage `<title>`/JSON-LD/og fields derive from blocks: page title = text of the **first** `heading` level-1 block (fallback `"The Family Archive"`); welcome = plain text of all `paragraph` blocks **before the first `forgeDocGroup`**, joined with `\n\n`. Headings level 2/3 anywhere render as `.seclabel`; additional level-1 headings after the first also render as `.seclabel`. | Deterministic derivation that round-trips the migrated content exactly. |
| D24 | Unsupported block types on the homepage (`quote`, lists, tables, `forgeImage`, `forgeFootnote`, …) are skipped at render with a build warning naming the type. The editor does not block inserting them (v1). | Keeps the renderer surface small; warnings make the gap visible instead of silent. |
| D25 | Position integers may have gaps after deletes; ordering is by value, and each positions-write renormalises that group to 0..n-1. New members append at `max+1`. | Gap-tolerant ordering avoids renumber-on-delete churn. |

## 3. Non-goals (v1)

- **Multi-group membership** — a document belongs to at most one group.
- **Nested groups** — flat list only.
- **Homepage themes** — the single Archive-serif index template only.
- Editing `footer_html` in the UI (it migrates into homepage meta and renders,
  but stays editable only via DB).
- Group-level publish controls, per-group pages, or group RSS.
- A second manual-order UI on the homepage block (`'manual'` sort mirrors
  Library `group_position` — single source of truth, by spec).
- Removing the legacy template path / `render_index` legacy variables
  (kept for the D15/D21 equivalence check; remove next sprint).

---

## Milestone M1 — Schema: groups table, document columns, migration runner

### Files

| Action | Path |
|---|---|
| create | `backend/notebook_forge/migrate.py` |
| modify | `backend/notebook_forge/models.py` |
| modify | `backend/notebook_forge/db.py` |
| create | `backend/tests/test_migrate.py` |

### models.py

Add after `Document`:

```python
class Group(Base):
    """Library document groups (single-group membership, v1)."""

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    color: Mapped[str] = mapped_column(String, default="#9c5a3c")  # '#rrggbb'
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
```

Add to `Document` (after `meta`):

```python
    kind: Mapped[str] = mapped_column(String, default="memoir")  # memoir | homepage
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True)
    group_position: Mapped[int] = mapped_column(Integer, default=0)
```

No relationship objects needed (queries are explicit selects, matching house style).

### migrate.py

```python
"""Idempotent column migrations. create_all() only creates missing TABLES;
new columns on existing tables are added here, guarded by PRAGMA table_info.
A one-time pre-migration backup of forge.db is written next to it."""
```

- `def _columns(conn, table: str) -> set[str]` — `PRAGMA table_info({table})`.
- `def run_migrations(engine: Engine, db_file: Path) -> None`:
  1. Compute pending DDL for `documents`:
     - `ALTER TABLE documents ADD COLUMN kind TEXT NOT NULL DEFAULT 'memoir'`
     - `ALTER TABLE documents ADD COLUMN group_id INTEGER REFERENCES groups(id)`
     - `ALTER TABLE documents ADD COLUMN group_position INTEGER NOT NULL DEFAULT 0`
  2. If any are pending and `db_file.exists()` and the backup
     `db_file.with_name("forge.db.bak-pre-groups")` does not exist, copy the
     DB file to it (`shutil.copy2`) **before** altering.
  3. Apply pending DDL in one `engine.begin()` block.

### db.py

In `make_engine`, after `Base.metadata.create_all(engine)` and before the FTS
DDL block:

```python
from .migrate import run_migrations
run_migrations(engine, db_path(ws))
```

(`create_all` creates `groups` first, so the FK reference is valid.)

### Tests (`backend/tests/test_migrate.py`)

1. Fresh workspace → engine boots, `documents` has `kind`/`group_id`/`group_position`, `groups` exists.
2. Simulated old DB: create an engine, then `ALTER TABLE documents DROP COLUMN`
   is not available in this SQLite — instead build an old-schema DB by
   creating a metadata copy without the new columns (use raw DDL:
   `CREATE TABLE documents(...)` matching the pre-change shape with one row
   inserted), then call `run_migrations` → columns appear, row data intact,
   `kind` backfilled `'memoir'`, backup file created.
3. Idempotency: second `run_migrations` call is a no-op and does not create a
   second backup.

### Acceptance

`make check` green; booting against an existing Sprint-1 workspace upgrades
in place, leaves `forge.db.bak-pre-groups` beside `forge.db`, and all 109
pre-existing backend tests still pass.

### Rollback note

Code rollback = git revert. Data rollback = stop the server and restore
`forge.db.bak-pre-groups` over `forge.db`. The added columns are otherwise
harmless to old code (old queries ignore them), so partial rollback is safe.

---

## Milestone M2 — Groups backend: service + API

### Files

| Action | Path |
|---|---|
| create | `backend/notebook_forge/groups.py` |
| modify | `backend/notebook_forge/api.py` |
| modify | `backend/notebook_forge/collection.py` (filter only) |
| create | `backend/tests/test_groups.py` |

### groups.py (service layer)

```python
"""Group CRUD + membership. A document belongs to at most one group
(group_id nullable); group_position orders documents within a group and
within the Ungrouped (NULL) bucket. Positions may gap after deletes;
every positions write renormalises to 0..n-1."""
```

Constants: `COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")`.

Functions (all take `session` first, mirror `services.py` style):

- `list_groups(session) -> list[Group]` — ordered by `sort_order, id`.
- `create_group(session, name, color) -> Group` — strip name; raise
  `ValueError` on empty name or bad color; `IntegrityError` propagates for
  duplicates (API maps to 409). `sort_order = (max or -1) + 1`.
- `update_group(session, group, *, name=None, color=None) -> Group` — same
  validation; only provided fields change.
- `reorder_groups(session, ids: list[int]) -> None` — raise `ValueError`
  unless `set(ids)` equals the set of existing group ids; assign
  `sort_order = index`.
- `delete_group(session, group) -> int` — fetch members ordered by
  `group_position`; set each `group_id=None` and
  `group_position = ungrouped_max + 1 + i` (preserving relative order, append
  to Ungrouped's end); delete the group row; return member count.
- `assign_document(session, doc, group: Group | None) -> Document` — set
  `group_id`; `group_position = max(position in destination bucket, default -1) + 1`;
  `services.record_change(session, doc, "edit", f"moved to group '{group.name}'")`
  or `"removed from group"` when `None`; no-op (no change row) if the group
  is unchanged.
- `set_positions(session, group_id: int | None, slugs: list[str]) -> None` —
  raise `ValueError` unless `slugs` is exactly the membership of that bucket
  (compare as sets and lengths); write `group_position = index`. No change rows (D19).
- `resolve_members(session, group_id: int, sort: str) -> list[Document]` —
  members of the group with `kind == 'memoir'`, ordered by:
  - `'manual'` → `group_position, id`
  - `'date_range'` → `(_start_year(slug), slug)` (import `_start_year` from
    `collection.py` — move it to `groups.py` and re-import in collection to
    avoid a cycle: **`_start_year` moves to `groups.py`**, `collection.py`
    imports it from there)
  - `'title_az'` → `title.casefold()`
  - `'last_updated'` → `updated_at` descending
  Unknown sort → `ValueError`.

### API additions (api.py)

Pydantic bodies: `GroupBody {name: str, color: str = "#9c5a3c"}`,
`GroupPatchBody {name: str | None = None, color: str | None = None}`,
`GroupOrderBody {ids: list[int]}`, `DocGroupBody {group_id: int | None}`,
`PositionsBody {group_id: int | None, slugs: list[str]}`.

| Route | Behaviour |
|---|---|
| `GET /api/groups` | `[{id, name, color, sort_order, members: [...]}]`. Members ordered by `group_position`; each member: `{slug, title, year_display, standfirst, description, word_count, group_position}`. `description` uses the same catalogue-setting lookup as `build_entries` (factor a helper `catalogue_descriptions(session) -> dict[str, str]` in `collection.py`); `word_count = count_words(doc.blocks)`; `title` = `meta.title or title`; `year_display` from meta. |
| `POST /api/groups` | 200 `{id, name, color, sort_order}`; 422 on `ValueError`; 409 on duplicate name (catch `IntegrityError`, `session.rollback()`). |
| `PUT /api/groups/order` | body `GroupOrderBody`; 200 `{"ok": true}`; 422 on mismatch. **Declare before** `PUT /api/groups/{group_id}` so `order` doesn't match the int path. |
| `PUT /api/groups/{group_id}` | 200 updated group; 404 unknown; 422/409 as above. |
| `DELETE /api/groups/{group_id}` | 200 `{"ok": true, "moved": n}`; 404 unknown. |
| `PUT /api/documents/{slug}/group` | 200 `{"ok": true, "group_id", "group_position"}`; 404 unknown doc/group; 409 if `doc.kind == 'homepage'` ("the homepage cannot be grouped"). |
| `PUT /api/documents/positions` | 200 `{"ok": true}`; 422 on membership mismatch. **Declare before** `GET /api/documents/{slug}` won't conflict (different method), but declare before `PUT /api/documents/{slug}/group`-style routes anyway to avoid `slug='positions'` capture: put it **above** all `/api/documents/{slug}…` routes. |

`GET /api/documents` (existing): add `"group_id": d.group_id`,
`"group_position": d.group_position`,
`"date_confirmed": d.meta.get("date_confirmed", True) is not False`
to each summary, and filter the listing to `kind == 'memoir'`
(`[d for d in docs if d.kind == "memoir"]` — or add the where-clause in
`services.list_documents`? **No** — keep `services.list_documents` returning
everything; filter in the API route, since the importer/tests use the service).

`build_entries` in `collection.py`: add `if doc.kind != "memoir": continue`
filter (D10).

### Tests (`backend/tests/test_groups.py`)

1. create/list/update/reorder happy paths; duplicate name raises; bad color raises.
2. `assign_document` appends to end; moving between groups appends to the
   destination's end; change rows recorded with the right summaries; re-assign
   to same group records nothing.
3. `delete_group` moves members to Ungrouped preserving relative order after
   existing ungrouped docs.
4. `set_positions` renormalises 0..n-1; membership mismatch raises; works for
   the `None` (Ungrouped) bucket.
5. `resolve_members` for all four sorts (fixture docs with distinct slugs
   `1930-a`, `1940-b`, titles, updated_at values).
6. API round-trip: `TestClient` create → assign → reorder → delete; homepage
   guard 409 deferred to M4 tests (no homepage doc exists yet here).
7. Deleting a grouped **document** (existing `DELETE /api/documents/{slug}`)
   leaves the group consistent — remaining members keep their order (gaps OK
   per D25).

### Acceptance

`make check` green. With `curl` against a dev server: groups CRUD works, doc
list shows `group_id`/`group_position`, deleting a group never deletes a
document.

---

## Milestone M3 — Library UI: grouping, sorting, drag, manage-groups

### Files

| Action | Path |
|---|---|
| create | `frontend/src/lib/librarySort.ts` |
| create | `frontend/src/views/ManageGroupsModal.tsx` |
| modify | `frontend/src/views/Library.tsx` |
| modify | `frontend/src/api.ts` |
| modify | `frontend/src/styles.css` (or wherever `.doc-card`/`.toolbar` styles live — locate by grepping `.doc-card`; add new classes alongside) |
| create | `frontend/src/test/librarySort.test.ts` |

### api.ts

New types/clients:

```ts
export interface GroupMember {
  slug: string; title: string; year_display: string; standfirst: string;
  description: string; word_count: number; group_position: number
}
export interface GroupInfo {
  id: number; name: string; color: string; sort_order: number; members: GroupMember[]
}
```

- `groups: () => GET /api/groups → GroupInfo[]`
- `createGroup: (name, color) => POST /api/groups`
- `updateGroup: (id, patch: {name?, color?}) => PUT /api/groups/{id}`
- `reorderGroups: (ids: number[]) => PUT /api/groups/order`
- `deleteGroup: (id) => DELETE /api/groups/{id}`
- `setDocumentGroup: (slug, groupId: number | null) => PUT /api/documents/{slug}/group`
- `setPositions: (groupId: number | null, slugs: string[]) => PUT /api/documents/positions`

`DocSummary` gains `group_id: number | null`, `group_position: number`,
`date_confirmed: boolean`.

### librarySort.ts (pure, unit-tested)

```ts
export type GroupBy = 'group' | 'none' | 'status' | 'format'
export type SortMode = 'manual' | 'date_range' | 'title_az' | 'last_updated' | 'attention'
export interface Bucket { key: string; label: string; color?: string; groupId?: number | null; docs: DocSummary[] }
```

- `startYear(slug)` — leading int before first `-`, else 9999 (mirror backend).
- `needsAttention(d)` — `d.pending_review > 0 || d.date_confirmed === false || d.targets.some(t => t.dirty)`.
- `sortDocs(docs, sort: SortMode): DocSummary[]`:
  - `manual` → `group_position` asc (stable tiebreak slug)
  - `date_range` → `(startYear, slug)`
  - `title_az` → `title.toLocaleLowerCase()` asc
  - `last_updated` → `updated_at` desc (null last)
  - `attention` → attention docs first (by `pending_review` desc, then title
    A–Z), then the rest by the `date_range` key
- `bucketDocs(docs, groupBy: GroupBy, groups: GroupInfo[]): Bucket[]`:
  - `group` → one bucket per group in `sort_order` (including empty groups,
    so headers are drop targets), then always-last
    `{key:'ungrouped', label:'Ungrouped', groupId:null}`
  - `none` → single bucket, no header rendered
  - `status` → fixed order: "Changes to push" (any dirty target), "Never
    published" (no PUBLISHED target), "Published · clean" (rest); omit empty
    buckets
  - `format` → one bucket per `source_type`, label = source_type, ordered A–Z;
    omit empty buckets
- Effective sort rule (D17): `effectiveSort(groupBy, sort)` returns
  `sort === 'manual' && groupBy !== 'group' ? 'date_range' : sort`.

### Library.tsx

Toolbar gains two `<select>`s after the status filter:

```
Group by: [Group ▾]  (group | none | status | format → labels "Group", "None", "Status", "Format")
Sort:     [Manual order ▾] (manual | date_range | title_az | last_updated | attention
           → labels "Manual order", "Date range", "Title A–Z", "Last updated", "Needs attention first")
```

plus a `Manage groups` button (opens the modal). State for both selects
initialises from / writes to localStorage (D18). On mount also fetch
`api.groups()` into state.

Rendering: `bucketDocs(visible, groupBy, groups)` → for each bucket (when
`groupBy !== 'none'`) render a header row
`<div className="group-header" data-bucket={key}>` containing a color dot
(`background: bucket.color`, only for real groups), the label, and a count
`(n)`. Then the bucket's docs through `sortDocs(docs, effectiveSort(...))`.

Drag behaviour (only when `effectiveSort === 'manual'`, i.e. group-by Group +
Manual):

- Each doc card gets a leading drag handle `<span className="drag-handle" draggable>`
  (icon `ti-grip-vertical`); `onDragStart` sets
  `e.dataTransfer.setData('text/nf-slug', d.slug)`.
- Doc cards: `onDragOver` (preventDefault + `.drop-before` class), `onDrop` →
  if the dragged slug is in the **same bucket**, compute the new slug order
  (move dragged before drop target) and call
  `api.setPositions(bucket.groupId ?? null, newOrder)`; if from a **different
  bucket**, call `api.setDocumentGroup(slug, bucket.groupId ?? null)` then
  `api.setPositions` to place it before the drop target. After either,
  re-fetch `api.listDocuments()` and `api.groups()`.
- Group headers (including Ungrouped): `onDragOver` highlight, `onDrop` →
  `api.setDocumentGroup(slug, bucket.groupId ?? null)` (appends to end), then
  re-fetch.

Row menu (all modes, not just manual): a kebab button (`ti-dots-vertical`) on
each card (stopPropagation so the card's open-click doesn't fire) opening a
small absolutely-positioned menu: one item per group ("Move to {name}") plus
"Remove from group" (only when `d.group_id != null`); each calls
`setDocumentGroup` + re-fetch. Close on outside click and Escape.

Non-destructive manual order (acceptance-critical): switching Sort to e.g.
Title A–Z and back to Manual must show the same manual order — guaranteed
because sorting is pure/display-only and positions are only written by
explicit drags.

Search-hits panel and status filter behave as today (buckets apply to the
filtered set).

Top nav: add a `Homepage` navlink between Library and Settings →
`window.location.hash = '#/homepage'` (route lands in M6; add the button now,
it 404s gracefully to library until M6 — acceptable within the same PR since
milestones merge together; Sonnet: implement nav in M6 if you prefer zero
dead links at intermediate commits).

### ManageGroupsModal.tsx

Modeled on `ChangesModal` (backdrop + box + Escape/close). Contents:

- List of groups in `sort_order`: color swatch button (click cycles to a
  popover of the 8 palette swatches, D8), inline name `<input>` (blur or Enter
  → `updateGroup`), member count, ↑/↓ buttons (swap with neighbour →
  `reorderGroups(fullIdList)`), delete button (confirm:
  `Delete group "{name}"? Its {n} documents move to Ungrouped.` →
  `deleteGroup`).
- Footer row: name input + palette swatch picker + "Create group" button
  (→ `createGroup`; disable on empty name; surface 409 as inline "name already
  in use").
- All mutations re-fetch `api.groups()` and bubble a `onChanged()` callback so
  Library re-fetches documents.

### CSS additions

`.group-header` (flex row, Fraunces-style small caps consistent with existing
`.toolbar` look — match the app's existing token classes), `.group-dot`
(10px circle), `.drag-handle` (grab cursor, muted), `.drop-before`
(2px top border accent), `.dragover` (header highlight), kebab menu styles,
modal swatch grid. Keep to the existing visual language (inspect existing
classes in the stylesheet before writing).

### Tests

`frontend/src/test/librarySort.test.ts` (vitest, pure functions): all five
sorts incl. attention ordering; bucket composition for each group-by; empty
groups present under `group`, absent under `status`/`format`; Ungrouped last;
`effectiveSort` fallback.

### Acceptance

- `make check` green.
- Live (preview tools): default view shows "The Memoirs" header *(after M5
  migration; before it, all docs sit under Ungrouped — verify final state
  after M5)*, drag handles visible, dragging reorders and persists across
  reload; dragging a card onto a header moves it; row menu moves it; sort
  switch hides handles and changes order non-destructively; Manage groups
  creates/renames/recolours/reorders/deletes with documents surviving group
  deletion.

---

## Milestone M4 — Homepage backend: kind, block renderer, fingerprint, publish flow

### Files

| Action | Path |
|---|---|
| create | `backend/notebook_forge/homepage.py` |
| modify | `backend/notebook_forge/blocks.py` (constants only) |
| modify | `backend/notebook_forge/services.py` |
| modify | `backend/notebook_forge/collection.py` |
| modify | `backend/notebook_forge/renderer.py` (render_index signature) |
| modify | `backend/templates/index.html.j2` |
| modify | `backend/notebook_forge/publish/service.py` |
| modify | `backend/notebook_forge/api.py` |
| create | `backend/tests/test_homepage.py` |
| modify | `backend/tests/test_collection.py`, `backend/tests/test_publish.py` (signature updates) |

### blocks.py

Add constants `FORGE_DOC_GROUP = "forgeDocGroup"`, `FORGE_DEDICATION = "forgeDedication"`,
`HOMEPAGE_SLUG = "homepage"` (put `HOMEPAGE_SLUG` here too — single import point).

### homepage.py

```python
"""Homepage-as-document: block-tree rendering of the collection index +
the resolved-group fingerprint that drives homepage dirty state.

The homepage's render depends on data OUTSIDE its own blocks (group
membership/order and member metadata), so its content hash must fold in a
fingerprint of everything a forgeDocGroup block renders. is_dirty then
detects library-side changes with zero event wiring."""
```

- `get_homepage(session) -> Document | None` — `kind == 'homepage'` singleton.
- `_walk(blocks)` — depth-first generator over blocks + children.
- `doc_group_blocks(blocks) -> list[dict]` — `forgeDocGroup` blocks in
  document order (recursive walk).
- `member_entry(session, doc, descriptions, *, with_blurbs, with_counts) -> dict`
  — `{"slug", "title": meta.title or title, "years": meta.year_display,
  "standfirst": meta.standfirst, "url": meta.canonical_url}` plus
  `"description"` when `with_blurbs` (from `descriptions` map) and
  `"word_count"` when `with_counts` (`count_words(doc.blocks)`).
- `group_listing_fingerprint(session, blocks) -> list[dict]` — for each
  `forgeDocGroup` block in order, with `props = block["props"]`,
  `gid = int(props["groupId"] or 0)`:
  - group missing or `gid == 0` → `{"groupId": gid, "missing": True}`
  - else `{"groupId": gid, "name": group.name, "members": [member_entry(...)
    for resolved members under props["sort"]]}` with `with_blurbs =
    props["showBlurbs"]`, `with_counts = props["showWordCounts"]`.
  (Layout/sort/show* props themselves are already inside the hashed blocks;
  only resolved data goes here. Color excluded per D6.)
- `homepage_body(session, doc) -> tuple[list[dict], list[str], dict]` —
  returns `(body_entries, warnings, derived)`:
  - walk **top-level** blocks of the homepage in order (children ignored for
    rendering, v1):
    - `heading` level 1, first occurrence → sets `derived["title"]`
      (plain `inline_text`), emits nothing (the template's masthead prints it)
    - `heading` (any other) → `{"kind": "seclabel", "text": inline_text(...)}`
    - `paragraph` (non-blank) → `{"kind": "intro", "html": inline_html(content)}`;
      first one before any group block gets `"lead": True`; blank skipped
    - `forgeDedication` → `{"kind": "dedication", "text": props["text"]}`
    - `divider` → `{"kind": "hr"}`
    - `forgeDocGroup` → resolve like the fingerprint; missing/unset group →
      warning `f"homepage: skipped group block (group #{gid} no longer exists)"`,
      emit nothing; empty group → warning
      `f"homepage: skipped empty group '{name}'"`, emit nothing; else
      `{"kind": "group", "label": group.name, "layout": props["layout"],
      "entries": [card entries]}` where each card entry is `member_entry`
      output + `"reading_time": reading_time(word_count)` when counts shown
    - anything else → warning
      `f"homepage: skipped unsupported block type '{btype}'"` (D24)
  - `derived["title"]` fallback `"The Family Archive"`;
    `derived["welcome"]` = plain text of paragraph blocks before the first
    `forgeDocGroup`, `"\n\n".join` (D23).

### services.py

Add:

```python
def effective_content_hash(session: Session, doc: Document) -> str:
    if doc.kind != "homepage":
        return content_hash(doc.blocks, doc.meta)
    from .homepage import group_listing_fingerprint
    meta = dict(doc.meta)
    meta["__group_listing__"] = group_listing_fingerprint(session, doc.blocks)
    return content_hash(doc.blocks, meta)
```

- `snapshot_document`: `content_hash=...` → `effective_content_hash(session, doc)`.
- `is_dirty`: final compare → `effective_content_hash(session, doc) != snap.content_hash`.
- `save_blocks` **keeps** plain `content_hash` for its before/after
  edit-detection (it only decides whether to log a change row).
- `rollback_to_snapshot` detail hash: leave as the stored `snap.content_hash`.

This is the exact fingerprint mechanism required by the feature spec: the
homepage hash now incorporates membership, order, and rendered metadata of
every referenced group, so a Library reorder/regroup/rename flips
`is_dirty(homepage, target)` on the next read with no extra bookkeeping.

### collection.py + renderer.py + template

- `root_files(...)` → returns `tuple[dict[str, str], list[str]]`
  `(files, warnings)`. Logic:
  - `hp = get_homepage(session)`
  - if `hp` is None → legacy path exactly as today, `warnings=[]`
  - else: `body, warnings, derived = homepage_body(session, hp)`;
    `title = derived["title"]`; `welcome = derived["welcome"]`;
    `dedication = ""` (handled by body); `footer = hp.meta.get("footer_html", "")`;
    `index_html = render_index(title=..., welcome=welcome, dedication="",
    entries=[], footer_text=footer, canonical_url=..., og_description=...,
    jsonld_script=..., body_entries=body)`.
    `catalogue.json`/`sitemap`/`robots`/`llms.txt` are built exactly as today
    from `build_entries` (memoirs only) — they are corpus artefacts, not
    homepage-block artefacts (D10/D11). `llms.txt`/JSON-LD use the derived
    title/welcome.
- `render_index(...)` gains keyword-only `body_entries: list | None = None`,
  passed to the template.
- `index.html.j2`: keep everything down to the `<h1 class="title">` line
  identical. Replace the welcome/dedication/hardcoded-hr-seclabel/entries
  section with:

```jinja
{% if body_entries is not none %}
  {% for e in body_entries %}
    {% if e.kind == 'intro' %}<p class="intro{% if e.lead %} lead{% endif %}">{{ e.html|safe }}</p>
    {% elif e.kind == 'dedication' %}<p class="dedication">{{ e.text }}</p>
    {% elif e.kind == 'hr' %}<hr class="div">
    {% elif e.kind == 'seclabel' %}<p class="seclabel">{{ e.text }}</p>
    {% elif e.kind == 'group' %}
      <p class="seclabel">{{ e.label }}</p>
      {% if e.layout == 'compact_grid' %}<div class="docgrid">{% endif %}
      {% for card in e.entries %}
      ...existing <a class="doc"> card markup verbatim, driven by card fields;
         omit <p class="desc"> when no description key or compact_grid;
         meta row always present with the Read → arrow; word-count spans only
         when card.word_count is defined...
      {% endfor %}
      {% if e.layout == 'compact_grid' %}</div>{% endif %}
    {% endif %}
  {% endfor %}
{% else %}
  ...the current welcome/dedication/hr/seclabel/entries markup, byte-for-byte
  unchanged (legacy path, D21)...
{% endif %}
```

  Important byte-fidelity details for the card partial: extract the existing
  card markup into a Jinja macro used by **both** paths so the two renderings
  cannot drift. `intro` paragraphs in the new path emit
  `{{ e.html|safe }}` — for migrated plain-text welcome paragraphs,
  `inline_html` of a plain text run produces the escaped text, identical to
  the legacy `{{ para.strip() }}` output. (`inline_html` escapes with
  `quote=False`, Jinja autoescape escapes quotes too — if the welcome text
  contains `"` or `'` the bytes could differ; the equivalence check in M5
  catches this; if it trips, switch `intro.html` emission to a plain-text
  field `{{ e.text }}` and drop inline styling support for intros — decide in
  favour of **plain text intros** pre-emptively? **No.** Keep HTML intros
  (italics in a welcome para must render); the current welcome contains no
  quotes (verify during M5; if it does, the seeding simply stays
  NEVER_PUBLISHED and the operator pushes once — acceptable).)
  Add the `.docgrid` CSS (D20) inside the template `<style>` block:

```css
.docgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:.9rem;margin:0 0 1.1rem;}
.docgrid .doc{margin:0;padding:1.1rem 1.2rem .9rem;}
```

### publish/service.py

- `build_bundle`: unchanged.
- `publish_document`: branch at the top:

```python
if doc.kind == "homepage":
    if target.kind == "drive":
        raise PermissionError("the homepage is not published to Drive targets")
    adapter = adapter or make_adapter(target, workspace)
    files, warnings = root_files(session, target=target, base_url=...)
    publish_fn = getattr(adapter, "publish_root_files", None)
    if publish_fn is None:
        raise PermissionError(f"target kind '{target.kind}' cannot publish the homepage")
    commit = publish_fn(files)
    snap = services.snapshot_document(session, doc, note=f"publish to {target.name}")
    services.mark_published(session, doc, target, snap)
    services.record_change(session, doc, "publish", f"published homepage to {target.name}",
        detail={"target": target.name, "snapshot_id": snap.id, "files": sorted(files),
                "warnings": warnings, "commit": commit if isinstance(commit, str) else None})
    return {"snapshot_id": snap.id, "files": sorted(files), "warnings": warnings,
            "commit": commit if isinstance(commit, str) else None}
```

- Regular-doc path: `bundle.root_files, root_warnings = root_files(...)` →
  adapter publish → existing snapshot/mark/record → then (D14):

```python
hp = get_homepage(session)
if hp is not None and target.kind != "drive" and services.is_dirty(session, hp, target):
    hp_snap = services.snapshot_document(session, hp, note=f"publish to {target.name} (with {doc.slug})")
    services.mark_published(session, hp, target, hp_snap)
    services.record_change(session, hp, "publish",
        f"homepage refreshed by publish of {doc.slug} to {target.name}",
        detail={"target": target.name, "snapshot_id": hp_snap.id})
```

  and include `"warnings": root_warnings` in the returned detail.
- Delete `rebuild_index()` (D12). Fix `rollback_and_republish` (unaffected).

### api.py

- `GET /api/documents/{slug}`: add `"kind": doc.kind` to the response.
- `_target_states`: skip `target.kind == "drive"` rows when
  `doc.kind == "homepage"`.
- Guards (all 409, D13): `DELETE /api/documents/{slug}` ("the homepage cannot
  be deleted"); `POST .../rename` ("the homepage slug is fixed");
  `DELETE .../publish/{target}` i.e. unpublish ("unpublishing the site index
  is not supported"); `POST .../polish` ("polish does not run on the
  homepage").
- Remove `POST /api/rebuild-index/{target_name}` and
  `PUT /api/settings/homepage` (+ `HomepageBody`); remove `"homepage"` key
  from `GET /api/settings` response (D12).
- `publish` route: response already spreads `detail` — warnings flow through.

### Tests (`backend/tests/test_homepage.py` + updates)

1. `homepage_body`: H1→derived title; paragraphs→intro with lead on first;
   level-2 heading→seclabel; dedication block; divider; group block resolves
   members under each sort; `showBlurbs/showWordCounts` toggle fields;
   `compact_grid` flows through; missing group → skipped + warning; empty
   group → skipped + warning; unsupported type (`quote`) → warning.
2. Fingerprint/dirty (the critical suite — create homepage doc + group + two
   memoir docs, publish homepage to a local-folder target, assert clean,
   then one mutation per test asserts `is_dirty` flips):
   - reorder members (`set_positions`)
   - move a doc out of the group / into it (`assign_document`)
   - rename a member's title (via `save_blocks` meta)
   - rename the **group**
   - edit member prose when `showWordCounts=true` (word count changes)
   - edit member prose when `showWordCounts=false` and `showBlurbs=false`
     **and title/standfirst unchanged** → homepage stays **clean**
   - recolour the group → stays clean (D6)
   - delete the group → dirty (fingerprint flips to `missing`)
3. Publish flow: homepage publish to LocalFolderTarget writes the five root
   files and marks PUBLISHED+clean; warnings returned for a deleted-group
   block; drive publish → PermissionError/409; regular doc publish with dirty
   homepage also snapshots+marks homepage (D14) and skips when homepage clean.
4. Guards: delete/rename/unpublish/polish homepage → 409.
5. `root_files` with no homepage doc → legacy output identical to before
   (regression-pin one rendered index against the pre-change fixture if one
   exists; otherwise assert structural markers: hardcoded seclabel present).
6. Update every existing caller/test of `root_files` for the new return tuple
   (`test_collection.py`, `test_publish.py`, any smoke usage —
   `grep -rn "root_files\|rebuild_index" backend scripts`).

### Acceptance

`make check` green; full M4 test list passing; no endpoint regressions in
`scripts/smoke.sh` (update it if it touches rebuild-index/settings-homepage).

---

## Milestone M5 — One-time data migration: Settings → homepage document (own milestone, with rollback)

### Files

| Action | Path |
|---|---|
| create | `backend/notebook_forge/homepage_migration.py` |
| modify | `backend/notebook_forge/api.py` (call at bootstrap) |
| create | `backend/tests/test_homepage_migration.py` |

### homepage_migration.py

`def ensure_homepage(session: Session) -> dict | None` — idempotent; returns a
detail dict when it migrates, `None` when the homepage already exists.

Steps (single transaction — the caller commits):

1. `get_homepage(session)` exists → return `None`.
2. Read `Setting 'homepage'`: `title` (fallback `"The Family Archive"`),
   `welcome`, `dedication`, `footer_html`.
3. Seed group: if **no groups exist**, create `Group(name="The Memoirs",
   color="#9c5a3c", sort_order=0)` and assign every `kind=='memoir'` document
   to it with `group_position` = chronological index
   (`(_start_year(slug), slug)` order). If groups already exist (operator
   created some between M3 and M5 deploys — same release, so realistically
   never), reuse the group named "The Memoirs" or create it empty; **do not**
   reassign existing memberships in that case.
4. Build blocks with `make_block`/`text_run` from `blocks.py`:
   - `heading` level 1 with `text_run(title)`
     (props `{"level": 1}`)
   - one `paragraph` per non-blank `welcome.split("\n\n")` segment
     (`text_run(seg.strip())`)
   - `forgeDedication` with props `{"text": dedication}` — only if dedication non-empty
   - `divider`
   - `forgeDocGroup` with props `{"groupId": str(group.id), "sort": "date_range",
     "showBlurbs": True, "showWordCounts": True, "layout": "list"}`
5. Create the document directly (not via `create_document` — set kind):
   `Document(slug=HOMEPAGE_SLUG, title="Homepage", kind="homepage",
   blocks=..., meta={"footer_html": footer_html})`; flush;
   `record_change(session, doc, "import", "migrated homepage from Settings")`;
   `reindex(session, doc)`.
6. **Equivalence check (D15/D21):** render `root_files(session)` (new path,
   homepage exists now) and the legacy index by calling `render_index` with
   the old settings values + `build_entries` + reading times — replicate the
   exact legacy `root_files` index construction in a private helper
   `_legacy_index_html(session, base_url)` (copy the current `root_files`
   body for index.html only). Compare the two `index.html` strings:
   - **byte-equal** → for each target with kind in `("github-pages",
     "local-folder")`: `snap = snapshot_document(...)` (one snapshot reused),
     `mark_published(session, doc, target, snap)`. Record change
     `"seeded PUBLISHED for {names}: migrated homepage renders byte-identical to the live index"`.
   - **not equal** → leave NEVER_PUBLISHED; record change
     `"homepage left unpublished: migrated render differs from legacy index (push to verify and go live)"`.
7. Leave the `Setting 'homepage'` row **untouched** (rollback data; no code
   reads title/welcome/dedication anymore; `footer_html` now lives in doc
   meta).
8. Return `{"migrated": True, "byte_identical": bool, "group_id": ...}`.

### Bootstrap call

In `api.py` `_state()`, after building the session factory:

```python
with state["factory"]() as session:
    from .homepage_migration import ensure_homepage
    ensure_homepage(session)
    session.commit()
```

(Also call it at the top of any CLI entry that opens a session, if
`cli.py` serves documents — check `cli.py`; if it only does imports/exports,
leave it.)

### Tests (`backend/tests/test_homepage_migration.py`)

1. Fresh workspace with a populated `homepage` setting + 3 memoir docs →
   migration creates group with chronological positions, homepage doc with
   exact block sequence (assert types/props/text in order), footer in meta.
2. Idempotent: second call returns `None`, no duplicate group/doc.
3. Byte-equivalence path: with fixture entries the two renders match → sync
   seeded PUBLISHED + clean for local-folder fixture target; tamper one
   member title between renders → not seeded.
4. Empty settings (no homepage row) → defaults used, doc still created,
   welcome empty → no intro paragraphs.
5. Dedication empty → no `forgeDedication` block.
6. Existing-groups guard: pre-create a group → migration creates/reuses "The
   Memoirs" without touching the other group's membership.

### Acceptance

Boot `make dev` against a copy of the real workspace: homepage doc appears;
`GET /api/documents` does **not** list it; `GET /api/documents/homepage`
returns kind `homepage`; sync pills for github-pages/local-folder are
PUBLISHED+clean if byte-identical (expected with the current corpus), else
never-published; Settings API no longer returns homepage fields.

### Rollback note (data)

The settings row is preserved and the migration is purely additive:
`DELETE FROM documents WHERE slug='homepage'` (cascades snapshots/sync/changes),
optionally `DELETE FROM groups` + `UPDATE documents SET group_id=NULL,
group_position=0`, then deploy the reverted code (which reads settings again).
Full fallback: restore `forge.db.bak-pre-groups`.

---

## Milestone M6 — Homepage frontend: nav tab, editor variant, dedication + group blocks, /group command

### Files

| Action | Path |
|---|---|
| modify | `frontend/src/App.tsx` |
| modify | `frontend/src/views/Library.tsx` (nav tab, if not done in M3) |
| modify | `frontend/src/views/Settings.tsx` (remove homepage section + nav) |
| modify | `frontend/src/views/Editor.tsx` |
| modify | `frontend/src/forge/schema.tsx` |
| create | `frontend/src/forge/ForgeDedicationView.tsx` |
| create | `frontend/src/forge/ForgeDocGroupView.tsx` |
| modify | `frontend/src/api.ts` (remove saveHomepage/rebuildIndex; add `kind` to DocDetail) |
| modify | stylesheet (dedication/group-block styles) |
| create | `frontend/src/test/forge-doc-group.test.tsx` |

### Routing & nav

- `App.tsx`: add `{ view: 'homepage' }` for hash `#/homepage` →
  `<Editor slug="homepage" onBack={toLibrary} />` (the editor reads `kind`
  from the fetched doc; no separate component).
- Top nav in Library: `Library | Homepage | Settings` (Homepage button sets
  `#/homepage`). Settings keeps its back-to-library button; add the same
  three-tab nav at the top of Settings for consistency? **No** — Settings
  layout stays as-is (single back button), only Library's topnav gains the
  tab. The editor's breadcrumb for the homepage shows
  `Library › Homepage` (crumb still navigates back to library).

### Settings.tsx

Delete the "Homepage (collection index)" `<h3>` section, its three fields,
Save homepage and all Rebuild-index buttons, plus their state/handlers
(`title/welcome/dedication/state/rebuilding`, `save`, `rebuild`). Keep
`targets` state only if still used (it isn't after removal — drop it and the
`s.targets` line). Sketch/polish/connections sections unchanged.

### Editor.tsx variant

`const isHomepage = doc.kind === 'homepage'` (add `kind: string` to
`DocDetail`).

When `isHomepage`:

- hide `MetaBar`, outline sidebar + rail and its header toggle button,
  Polish UI, Delete panel, Re-ingest (D22)
- header titles show `Homepage` and the muted line
  `Site index — push to publish`
- PendingPanel: rendered as-is (backend already filtered drive rows); hide
  the per-row Unpublish button when `isHomepage`
- SnapshotsPanel unchanged
- after a push completes, if the publish response detail contains a non-empty
  `warnings` array, `alert("Published with warnings:\n" + warnings.join("\n"))`
  — thread `warnings` through `api.publish`'s return type
  (`detail?: { warnings?: string[] }`)
- stale-data refresh (concurrent-edit edge): `useEffect` adding a `focus`
  listener on `window` that re-fetches `api.getDocument(slug)` and calls
  `setTargets(fresh.targets)` (only when `isHomepage`); the group block views
  refresh themselves (below)
- slash menu: replace the plain `<BlockNoteView ... />` with

```tsx
<BlockNoteView editor={editor} onChange={onChange} theme="light" slashMenu={!isHomepage ? undefined : false}>
  {isHomepage && (
    <SuggestionMenuController
      triggerCharacter="/"
      getItems={async (q) =>
        filterSuggestionItems(
          [...getDefaultReactSlashMenuItems(editor), docGroupSlashItem(editor)], q)}
    />
  )}
</BlockNoteView>
```

  with `docGroupSlashItem` exported from `schema.tsx`:

```ts
{ title: 'Document group', aliases: ['group'], group: 'Forge',
  subtext: 'Curated list of library documents',
  icon: <i className="ti ti-folders" />,
  onItemClick: () => insertOrUpdateBlock(editor, { type: 'forgeDocGroup' }) }
```

  (imports: `SuggestionMenuController`, `getDefaultReactSlashMenuItems`,
  `filterSuggestionItems` from `@blocknote/react`/`@blocknote/core`,
  `insertOrUpdateBlock` from `@blocknote/core` — verify exact module paths
  against the installed 0.51 typings and adjust imports only).

### schema.tsx — two new blocks

```ts
export const forgeDedicationSpec = createReactBlockSpec(
  { type: 'forgeDedication', propSchema: { text: { default: '' } }, content: 'none' },
  { render: ({ block, editor }) => (
      <ForgeDedicationView text={block.props.text}
        onChange={(text) => editor.updateBlock(block, { props: { ...block.props, text } })} /> ) },
)

export const forgeDocGroupSpec = createReactBlockSpec(
  { type: 'forgeDocGroup',
    propSchema: {
      groupId: { default: '' },           // numeric string; '' = unset
      sort: { default: 'manual', values: ['manual', 'date_range', 'title_az', 'last_updated'] },
      showBlurbs: { default: true },
      showWordCounts: { default: true },
      layout: { default: 'list', values: ['list', 'compact_grid'] },
    },
    content: 'none' },
  { render: ({ block, editor }) => (
      <ForgeDocGroupView props={block.props as ForgeDocGroupProps}
        onChange={(patch) => editor.updateBlock(block, { props: { ...block.props, ...patch } })} /> ) },
)
```

Register both in `forgeSchema.blockSpecs`. The block stores **only** the
reference + options — never a member list (resolution happens at render time,
per spec).

### ForgeDedicationView.tsx

Styled to match the published `.dedication` (Fraunces italic, accent-deep,
centered): a single-line `<input className="forge-dedication-input">` with
placeholder "Dedication…", value = `text`, committing on blur/Enter (same
commit pattern as `ForgeFootnoteView` — read that file and mirror it).

### ForgeDocGroupView.tsx

A non-prose card (`.forge-docgroup`):

- on mount and on `window` `focus`: `api.groups()` → state.
- header row: `ti-folders` icon + group `<select>` (options: "Choose a
  group…" for `''`, then each group name; value `groupId`) + the group's
  color dot.
- config row: sort `<select>` (Manual order — mirrors Library | Date range |
  Title A–Z | Last updated), `showBlurbs` checkbox "Blurbs",
  `showWordCounts` checkbox "Word counts", layout `<select>` (List | Compact
  grid). Each control patches props via `onChange`.
- body:
  - `groupId === ''` → muted "Choose a group to list its documents."
  - group not found in the fetched list → warning state
    (`.forge-docgroup.warn`, `ti-alert-triangle`):
    "This group no longer exists — the block will be skipped at publish."
  - empty group → muted "'{name}' has no documents — this block will be
    skipped at publish."
  - else: member preview — first 5 members **in the selected sort order**
    (client-side resort of `members` using the same comparators as
    `librarySort.ts`; for `manual` use `group_position` as delivered) as
    rows `title · years`, then "+ {n−5} more" when over 5.
- Note in a muted footer line when sort = Manual: "Manual order follows the
  Library." (single source of truth, by spec — no reorder UI here).

### Tests (`frontend/src/test/forge-doc-group.test.tsx`)

Mock `api.groups`. Assert: unset state renders the chooser hint; selecting a
group patches `groupId`; member preview renders titles in sort order and the
"+N more" line; missing-group warning text renders when `groupId` points
nowhere; checkbox toggles patch props. Plus a smoke test that `forgeSchema`
creates an editor containing `forgeDocGroup`/`forgeDedication` (extend the
existing `forge-blocks.test.tsx` pattern).

### Acceptance

- `make check` green.
- Live: Homepage tab opens the migrated document — H1 title, welcome
  paragraphs, dedication block, divider, group block previewing the seven
  memoirs chronologically; typing `/group` inserts a configurable block;
  editing anything makes github-pages/local-folder rows dirty; Push to
  local-folder writes `~/NotebookForge-workspace/exports/site/index.html`
  whose rendered content matches the editor (verify via the `/site/` mount);
  Library reorder of a grouped doc flips the Homepage pending rows to dirty
  after tab focus; Settings shows no homepage section and no Rebuild-index
  buttons.

---

## Milestone M7 — Edge-case hardening, integration tests, docs

### Files

| Action | Path |
|---|---|
| modify | `backend/tests/test_homepage.py` (integration additions) |
| modify | `scripts/smoke.sh` (if it references removed endpoints; add a homepage GET) |
| modify | `README.md` (short "Groups & Homepage" section in the 5-minute tour) |
| modify | `SPRINT_REPORT.md` (append a sprint addendum describing what shipped) |

### Edge cases — explicit coverage checklist

Each gets an automated test (most already specified above; this is the
master list — verify all are green):

1. **Deleting a grouped document** — group stays consistent, homepage
   fingerprint changes → homepage dirty (test: publish homepage, delete a
   member doc via API, assert dirty).
2. **Deleting a group** — documents move to Ungrouped preserving order;
   homepage block referencing it renders the editor warning state (frontend
   test) and is skipped with a publish warning (backend test); homepage goes
   dirty.
3. **Homepage block for an empty group** — editor shows the muted
   skip-notice; publish skips it with a warning; publishing succeeds.
4. **Duplicate lowercase "junior · 1930–1945" test document** — cleanup
   note only, NOTHING automated deletes it: the migration will sweep it into
   "The Memoirs" like every other memoir doc. **Operator action after
   deploy:** open it from the Library and use Delete document (or leave it;
   it was always on the published index too). Record the note in the
   SPRINT_REPORT addendum verbatim so it isn't forgotten.
5. **Concurrent edit: homepage open while the library reorders** — homepage
   autosave PUTs only blocks+meta; group membership/order live in
   `documents`/`groups` rows, so the autosave cannot clobber the reorder
   (test: interleave `save_blocks(homepage)` and `set_positions`, assert the
   final fingerprint reflects the reorder and `is_dirty` is true). The
   editor's focus-refresh (M6) restores UI freshness; block previews
   re-fetch on focus.
6. **Manual order is non-destructive** — switch sort away and back in the
   Library: positions unchanged (covered by pure-function design + vitest).
7. **Homepage publish to a target with no root-file support** (drive) — 409,
   message stable.
8. **Slug collision** — `ingest` creating a doc while `slug='homepage'`
   exists: ingestion derives slugs from date+title; if one ever collides the
   existing unique-constraint failure path applies. No code change; covered
   by the unique index.

### Integration test (backend, the end-to-end story)

One test that scripts the full loop with a local-folder target:
migrate (M5 helper) → homepage publish → clean → `set_positions` reorder →
homepage dirty → republish → clean → rename a member title via `save_blocks`
→ dirty → publish the *member* document → homepage auto-marked clean (D14)
→ delete the group → dirty with warning on next publish → final index.html
contains no card section but the intro paragraphs survive.

### Acceptance (whole feature)

- `make check` green (expect ≈135+ backend / ≈30 frontend tests).
- `scripts/smoke.sh` green.
- Manual live pass per M3/M6 acceptance lists, against a **copy** of the real
  workspace (`NOTEBOOK_FORGE_WORKSPACE=` a copied dir) before touching the
  real one.
- No pushes to the live `github-pages` target during verification — use
  local-folder; live push is the operator's call.

---

## Risks

| Risk | Mitigation |
|---|---|
| SQLite `ALTER TABLE` on the live workspace corrupts/locks the DB | WAL mode + idempotent guarded DDL + automatic `forge.db.bak-pre-groups` backup before first alteration (M1). |
| Migrated homepage render differs from the live index (quote-escaping or strip subtleties in welcome text) | D15 equivalence check refuses to seed PUBLISHED unless byte-identical; worst case the operator reviews and pushes once. Shared Jinja macro (D21) eliminates card-markup drift. |
| `effective_content_hash` runs `count_words` over every grouped member on each `is_dirty` call (per target, per doc list render) | Corpus is 7 documents; `_target_states` already iterates targets×docs with per-doc queries. If the library grows, memoise per-request — explicitly deferred, do not build now. |
| BlockNote 0.51 API drift for `SuggestionMenuController`/`insertOrUpdateBlock` | Marked verify-imports-only in M6; the two existing custom blocks prove `createReactBlockSpec` works; slash-menu wiring is the only new BlockNote surface. |
| Removing `rebuild-index`/`settings/homepage` endpoints breaks an unnoticed caller | `grep -rn "rebuild-index\|rebuildIndex\|saveHomepage\|settings/homepage" backend frontend scripts` before deleting; smoke.sh updated in M7. |
| Homepage marked clean by D14 while a drive publish skipped root files | D14 explicitly excludes drive targets; homepage has no drive sync rows at all. |
| Native HTML5 DnD quirks (Safari drag image, dragover throttling) | Interactions kept minimal (insert-before + drop-on-header); row-menu fallback covers every move without drag. |
| Old snapshots' `content_hash` (plain hash) vs new `effective_content_hash` for the homepage | The homepage is new — its first snapshot is already effective-hash. Memoir docs: `effective == plain` by definition. No backfill needed. |

## Operator notes (post-deploy, for Chris — copy into SPRINT_REPORT addendum)

1. New ingests are **Ungrouped** and won't appear on the published homepage
   until you add them to a group (D11).
2. The duplicate lowercase "junior · 1930–1945" test document is still in the
   library; delete it from its editor page when convenient (nothing automated
   touches it).
3. If the homepage shows "never published" after migration, the new renderer
   didn't byte-match the legacy index — open the Homepage tab, eyeball it,
   and Push to local-folder first, then github-pages.

---

## Kickoff prompt for Sonnet

Copy-paste exactly:

> Implement the plan in `docs/PLAN_groups_and_homepage.md` end to end, in
> milestone order M1→M7. The plan is binding: every design decision is
> already made in its §2 "Locked decisions" table and the per-milestone
> specs — do not redesign, substitute libraries, or skip the listed tests.
> Work on a feature branch off `main`. Before starting, read
> `SPRINT_REPORT.md`, `backend/notebook_forge/{models,services,collection,api}.py`,
> `backend/notebook_forge/publish/service.py`,
> `frontend/src/views/{Library,Settings,Editor}.tsx`, and
> `frontend/src/forge/schema.tsx` so the plan's references are grounded.
> Commit at every milestone gate with conventional commits, keeping
> `make check` green at each gate; if a gate fails after 3 distinct fix
> attempts, record the failure honestly in the commit and continue.
> Hard guardrails from `BUILD_PLAN.md` §2 still apply: never push to any
> repo except origin, never run `git add -A`, never touch
> `/Users/cs/ClaudeCode/MemoirForge` or any family-history clone, no live
> publishing to the real github-pages target during verification — use a
> copied workspace (`NOTEBOOK_FORGE_WORKSPACE`) and the local-folder target
> for all live checks. The real workspace DB must only ever be upgraded by
> the M1 migration (which backs it up first). When all milestones pass,
> run the M7 manual verification with the preview tools, append the sprint
> addendum + operator notes to `SPRINT_REPORT.md` as specified in M7, and
> push the branch.
