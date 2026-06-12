# Build plan — forgeNarrative blocks (author's reflective voice)

**Author:** Fable 5 (architect pass, 12 June 2026).
**Executor:** Claude Sonnet, in a later session. This plan is binding: every
decision is made and recorded with rationale below. Do not redesign,
substitute, or skip listed tests.

The source memoirs contain paragraph-length passages of the author's
reflective voice set entirely in italics. This plan turns them into a
semantic block type — `forgeNarrative` — restyled for readability (upright,
body-size, warm tinted panel), clearly distinct from footnotes, across the
HTML edition, the editor, the NotebookLM-safe Drive edition, all ingest
paths, and a one-time migration of the stored library.

Relationship to `docs/PLAN_groups_and_homepage.md`: that plan **already
shipped** (Sprint 3, M1–M7 — see SPRINT_REPORT.md). The homepage is a
first-class document with its own slash menu; this plan adds `/narrative`
to **both** slash-menu branches and a `narrative` entry kind to
`homepage_body` + `index.html.j2` so the block works on the homepage too.
Nothing here conflicts with that feature.

---

## 1. Current state (verified by reading the code, 12 June 2026)

- **Canonical format** (`backend/notebook_forge/blocks.py`): BlockNote block
  JSON. Custom blocks so far: `forgeImage`, `forgeFootnote`,
  `forgeDocGroup`, `forgeDedication` (constants at the top of blocks.py).
  Inline runs are `{type:"text", text, styles}` with boolean styles
  (`italic`, `bold`, …, plus the custom `fnRef`), and
  `{type:"link", href, content:[…]}`. `content_hash` strips ids;
  `plain_text` handles unknown block types via the generic `inline_text`
  branch — so a new inline-content block type indexes into FTS with **no
  change** to `plain_text`.
- **HTML → blocks** (`parser.py`): `parse_article` walks `<article>`
  children; `p`→paragraph, `h2/h3`→heading, `figure`→forgeImage,
  `aside.footnote`→forgeFootnote, `blockquote`→quote, lists/hr/table to
  built-ins; generic `div/section` recurses. Styles merge via
  `_merge_styles` (`em/i`→`italic`); `sup.fn-ref`→`fnRef` style.
- **Blocks → HTML** (`renderer.py` + `backend/templates/page.html.j2`):
  `build_body` produces template entries (`p`, `h2/h3`, `figure`,
  `footnote`, `blockquote`, `li`→grouped `list`, `hr`, `table`); the first
  non-empty paragraph gets `lead`. Template is the ported MemoirForge page;
  theme tokens in `:root` — `--paper:#faf8f3`, `--ink:#2a2520`,
  `--ink-soft:#5b5248`, `--accent:#9c5a3c`, `--rule:#e4ddd0`.
- **Shipped footnote CSS** (page.html.j2 ~349–377): `sup.fn-ref` is `.62em`
  Fraunces, `var(--accent)`; `aside.footnote` is **`.86rem`**, `color:
  var(--ink-soft)`, **`border-left:2px solid var(--accent)`**, no
  background tint, with a bold `span.fn-num` marker. The editor twin
  (`frontend/src/index.css` ~441–477): `.forge-footnote` 13px, grey
  (`--color-text-secondary`), 2px info-coloured left border, marker input.
  → The narrative styling below differs on **size** (1em vs .86rem/13px),
  **tint** (warm `#F1EADA` panel vs none), and **marker** (none vs
  numbered).
- **Editor** (`frontend/src/forge/schema.tsx`, `views/Editor.tsx`,
  BlockNote **0.51.4**, core/react/mantine only): custom blocks via
  `createReactBlockSpec`, all current ones `content:'none'`. Slash menu has
  two branches in Editor.tsx (~line 809): homepage (defaults + dedication +
  docGroup) and non-homepage (defaults minus Image, plus Photo/Figure). No
  `SideMenuController` customisation exists yet.
- **Ingest paths converge**: house-style HTML via `parser.parse_page` (used
  by `importer.import_document`); DOCX/PDF via vendored extractors →
  `DocumentDraft` with **Markdown-ish emphasis** in `TextBlock.text` →
  `ingestion.draft_to_blocks` → `_md_inline_runs` (alias of
  `polish.textmap.polish_text_to_content`) which sets `styles.italic` from
  `*…*`/`***…***`. `reingest_document` and `reimport.reimport_document`
  both go through `ingestion._extract_blocks` → `draft_to_blocks`. So one
  post-pass over the canonical block tree covers DOCX, PDF, re-ingest and
  re-import; the HTML importer needs the same post-pass called once.
- **Captions/footnotes are excluded by construction**: in DOCX/PDF
  extraction, captions are detected before body blocks exist
  (`detected_captions`), and footnotes land in `draft.footnotes` →
  forgeFootnote props. In HTML, captions/footnote bodies are props strings.
  A paragraph-block-only rule can never touch them.
- **Drive renderer state**: REAL, not mocked. The Drive deliverable is the
  NotebookLM-safe **Markdown** (`safe_edition.render_safe_markdown`)
  uploaded as `text/markdown` and converted by Drive to a Google Doc
  (`publish/drive.py` `DriveTarget.publish`; real `GoogleDriveClient` since
  Sprint 2; NotebookLM ingestion verified live). Footnotes there are
  blockquotes with a bold marker: `> **[N]** text`. Markdown→Doc conversion
  offers **no colour control**; available distinctions are indentation
  (blockquote), emphasis, and structural markers — this constrains D8.
- **Round-trip harness**: `importer.roundtrip_document` renders a stored doc
  and `domcompare.compare`s it against the published file
  (reports/roundtrip.md, ≥99% gate); `tests/test_renderer.py` has the M3
  `render(parse(x))` idempotency gate over `backend/tests/fixtures/*.html`;
  `tests/test_parser.py` covers fragments via `parse_fragment`.
- **Dirty state**: `services.effective_content_hash` already special-cases
  the homepage (folds the group fingerprint into the hash). Precedent for
  folding derived render inputs into dirty detection.
- **Settings**: `Setting` rows keyed by name (`sketch`, `polish`,
  `homepage`…); `GET /api/settings` returns sections; `PUT
  /api/settings/{section}` upserts. Settings.tsx renders labelled-row
  sections.
- **Polish**: `polish/textmap.py` `POLISHABLE = ("paragraph", "heading",
  "quote", "bulletListItem", "numberedListItem")`; non-listed types are
  skipped from LLM polish.
- **The corpus** (verified against `vendor-readonly/family-history/rfs/`):
  full-italic `<p><em>…</em></p>` paragraphs exist in exactly two memoirs —
  **part-2 (16)** and **part-4 (6)**, including two `<em><strong>` pseudo-
  heading lines ("Dining In The Mess", "A MARRIED QUARTER DISASTER") and an
  italic quoted letter ("We commenced at Quillberry…"). The other five
  memoirs have none. No `<em>` directly inside footnote asides.

## 2. Locked decisions and rationale

Decisions A–F from the feature brief are restated where needed; D-numbers
are the implementation decisions this plan adds.

| # | Decision | Rationale |
|---|---|---|
| D1 | New block type `forgeNarrative`, **inline content** (`content:'inline'` in BlockNote; `content: [runs]` in stored JSON), `props: {}` (none in v1). | Typing must behave like a paragraph (brief C). Inline content gives caret/selection/formatting for free; props-based text (like forgeFootnote) would not. |
| D2 | Theme tokens: add `--narr-bg:#f1eada; --narr-border:#b8a580;` to `:root` of **both** `page.html.j2` and `index.html.j2`, and `--narrative-bg:#f1eada; --narrative-border:#b8a580;` to `:root` of `frontend/src/index.css`. | Brief A's reference values, made tokens so future themes can override. Editor token names follow index.css's existing `--*-bg` convention. |
| D3 | Conversion **strips `italic`** from every text run (links recursed); "Convert to paragraph" **re-adds `italic`** to every text run except `fnRef` runs. | The block type now carries the semantics; rendered output is upright (brief A) and round-trips unambiguously. Re-italicising on convert-back restores the source emphasis exactly, making the two commands true inverses. `fnRef` runs are reference markers, never italicised. |
| D4 | Fully-italic test ignores: text runs containing **no alphanumeric character** (whitespace/punctuation), and runs styled `fnRef`. Links count via their inner text runs. At least one italic run containing a word character is required (⇒ empty/blank paragraphs never convert). | Brief B "ignoring whitespace and punctuation outside italic runs"; footnote markers sit outside the italics in the source; empty-paragraph edge closed. |
| D5 | Rule B applies **only to `type=="paragraph"` top-level blocks**. Headings, quote blocks, list items, captions, footnotes are excluded by construction (different types/props). Italic quotations *authored as paragraphs* (the Quillberry letter) **do convert** — the editor's "Convert to paragraph" is the remedy, per the brief. The two `<em><strong>` pseudo-heading lines also convert (entirely italic), keep their `bold` runs, and are <12 words so the report flags them for review. | Matches brief B exactly; the corpus has zero real `<blockquote>` elements, so the quotation case only arises in paragraph form. |
| D6 | Conversion happens as a **post-pass on the canonical block tree** — `narrative.convert_full_italic_paragraphs(blocks)` — called from `ingestion._extract_blocks` (covers DOCX, PDF, re-ingest, re-import) and `importer.import_document` (house-style HTML). The parser itself stays a faithful HTML→blocks mapping. | One implementation, three ingest paths (brief B). Keeping `parse_article` faithful means `parse_fragment` unit tests stay byte-honest and the conversion is independently testable/reportable. |
| D7 | HTML output: consecutive `forgeNarrative` blocks merge into one `<div class="narrative">` containing one `<p>` per block (brief A). The parser maps `div.narrative` back to one forgeNarrative block **per child `<p>`**, skipping `p.narrative-label`. A forgeFootnote between two narrative blocks legitimately splits the panel in two (not consecutive). | Merged panel + split-back gives idempotent round-trip (brief F). Label line is derived furniture, parsed away like ToC/anchors. |
| D8 | Drive/NotebookLM representation: narrative renders as a **Markdown blockquote with no marker**, consecutive blocks merged into one blockquote with `>`-separated paragraphs. Upright (no `*…*`). No label text ever (brief E). | The Drive deliverable is Markdown→Doc conversion (verified in §1); colour is **not expressible** there, so "indentation + colour" degrades to indentation. Distinction holds: body text is unindented; footnotes are blockquotes **with** a bold `[N]` marker; narrative is the unmarked blockquote. Theoretical collision with `quote` blocks is accepted — the corpus contains none (synthetic-only). Switching the Drive pipeline to HTML upload for colour would jeopardise the verified NotebookLM flow and is out of scope. |
| D9 | Label: `Setting` row `narrative` = `{"label": ""}` (workspace default, empty ⇒ no label). Per-document override = `doc.meta["narrative_label"]`; **key presence** decides: key present (even `""`) ⇒ use it, absent ⇒ inherit workspace. Effective label resolved by `narrative.effective_narrative_label(session, doc)`. When non-empty it renders as a small-caps sans line at the top of **each** HTML panel. Not rendered on homepage panels and never in the Drive edition. | Brief A. Key-presence tri-state lets one document opt out (`""`) while others inherit. Homepage/Drive exclusion keeps those surfaces label-free without extra settings. |
| D10 | The **editor does not render the label**. | The label is derived publish furniture, exactly like heading anchors and figure ToC entries, which the editor also doesn't show. Avoids fetching settings inside block renders. Brief says don't surface prominently. |
| D11 | Dirty detection: `services.effective_content_hash` folds `meta["__narrative_label__"] = effective_narrative_label(...)` into the hash **iff** the doc's top-level blocks contain a forgeNarrative. | Without this, changing the workspace label would change every published page without marking anything dirty. Folding only when narrative blocks exist avoids dirtying the whole library on an irrelevant setting change. Direct precedent: `__group_listing__` for the homepage. Old snapshots are unaffected (no doc has narrative blocks until migration, which snapshots + dirties anyway). |
| D12 | Editor "block menu" = BlockNote's **drag-handle menu** via `SideMenuController`: "Convert to narrative" shown on `paragraph` blocks, "Convert to paragraph" shown on `forgeNarrative` blocks. The formatting-toolbar BlockTypeSelect is NOT extended. | The drag-handle menu is BlockNote 0.51's per-block menu and needs no schema changes for conditional items. One surface is enough for v1. |
| D13 | Migration runs via **CLI only** (`narrative-migrate --dry-run|--apply`), mirrors the `reimport` command pattern, and is guarded by a `Setting` row `narrative_migration` = `{"applied_at": iso, "converted": {slug: n}}`. A second `--apply` refuses unless `--force`. Homepage (`kind=="homepage"`) is **excluded**. | Brief D wants a deliberate two-phase operator action, not a bootstrap hook (contrast `ensure_homepage`, which is idempotent-by-content; this one is not — an operator who converts a false positive *back* to an italic paragraph must not have it re-converted by a casual re-run). Homepage welcome text is not author memoir narrative, and `forgeDedication` already owns the homepage's italic line. |
| D14 | Migration apply: per affected document — `services.snapshot_document(note="before narrative migration")`, then `services.save_blocks(summary=f"narrative migration: {n} paragraph(s) converted")`. Dirty flags need no extra code (the content hash changes). Rollback = restore that snapshot via the existing snapshot browser/API. | Brief D's snapshot + rollback requirement on existing machinery. |
| D15 | The round-trip harness's hard gate changes for affected docs: the **new invariant is self-idempotence** — `parse(render(blocks))` equals `blocks` (modulo ids) and `render(parse(render(blocks)))` is DOM-equal to `render(blocks)` at 100%. First-pass similarity vs the *published* files becomes informational for part-2/part-4 (they intentionally diverge on exactly the converted paragraphs until republished); the other five memoirs keep the ≥99% published-DOM gate. | Brief F. The published pages were generated pre-feature; byte-fidelity to them on narrative passages is now *wrong* by definition. Idempotence is the durable property. |
| D16 | `forgeNarrative` is added to polish's `POLISHABLE` tuple (serialises as kind `p`). | It is body prose; typo cleanup applies. One-line change, covered by a test. |
| D17 | Import/ingest responses and change-log entries report `narrative_conversions` (count) and `narrative_flagged` (previews of <12-word conversions). No new ingest UI in v1 — the change log and migration report are the human-review surfaces. | Brief B's flagging requirement with minimal surface area. |
| D18 | Word count for the <12-word flag = `len(plain.split())` over the paragraph's `inline_text`. Preview = first 90 chars of plain text + `…` when truncated. | Deterministic and cheap; matches how the corpus text reads. |

## 3. Non-goals (v1)

- Per-block label overrides (label is workspace + per-document only).
- Multiple narrative styles or props (`forgeNarrative` has no props).
- Theme variants beyond the Archive serif theme.
- Auto-detection heuristics beyond rule B (no length/keyword scoring).
- Changing the Drive pipeline to HTML upload for colour fidelity.
- An ingest-review UI for flagged conversions (change log + report only).
- Enter-key continuation keeping the narrative type (BlockNote default
  behaviour is accepted; see M5 acceptance).

---

## Milestone M1 — Canonical rule: `narrative.py` + block constant

### Files

| File | Change |
|---|---|
| `backend/notebook_forge/blocks.py` | add `FORGE_NARRATIVE = "forgeNarrative"`; extend module docstring's custom-block list (`forgeNarrative — content: inline runs; props: {}`) |
| `backend/notebook_forge/narrative.py` | **new** — the whole rule + label resolution |
| `backend/tests/test_narrative.py` | **new** |

### narrative.py (complete spec)

```python
"""forgeNarrative: the author's reflective voice (full-italic source
paragraphs become a semantic block, rendered upright in a tinted panel).

Rule B (locked): a paragraph converts iff its ENTIRE text content is
italic, ignoring runs with no alphanumeric character and fnRef marker
runs. Paragraph blocks only — headings, quotes, list items, captions and
footnotes are excluded by construction.
"""

FLAG_WORDS = 12  # conversions under this word count are flagged for review

def _has_word(text: str) -> bool          # any(c.isalnum() for c in text)

def _runs_all_italic(content) -> tuple[bool, bool]:
    # returns (all_italic, saw_italic_word)
    # text run: fnRef-styled or no-word → ignore; else requires
    #   styles.get("italic") truthy
    # link run: recurse into run["content"]
    # unknown run types → not italic (be conservative)

def is_fully_italic(content: list | None) -> bool:
    # _runs_all_italic + at least one italic word-bearing run

def strip_italic(content: list) -> list:
    # deep-copied runs with "italic" removed from styles dicts
    # (links: recurse into content; fnRef runs returned unchanged)

def add_italic(content: list) -> list:
    # inverse for the editor-parity tests: italic=True on every text run
    # EXCEPT fnRef runs; links recurse

def conversion_report_entry(block) -> dict:
    # {"words": int, "preview": str, "flagged": words < FLAG_WORDS}
    # via blocks.inline_text + D18

def convert_full_italic_paragraphs(blocks) -> tuple[list, list[dict]]:
    # returns (new_blocks, conversions). Non-mutating (build a new list;
    # converted blocks keep their existing id). For each top-level block:
    #   type=="paragraph" and is_fully_italic(content) →
    #     {**block, "type": FORGE_NARRATIVE, "props": {},
    #      "content": strip_italic(content)}
    #     conversions.append(conversion_report_entry(block))
    #   anything else (incl. forgeNarrative) → unchanged  → idempotent
    # children are never visited: list-item children are list items by
    # type, and paragraphs never nest in this corpus.

def narrative_label_setting(session) -> str:
    # Setting "narrative" value {"label": str}; missing row → ""

def effective_narrative_label(session, doc) -> str:
    # doc.meta["narrative_label"] if "narrative_label" in doc.meta
    # else narrative_label_setting(session)   (D9 key-presence tri-state)
```

### Tests (`backend/tests/test_narrative.py`)

1. Fully italic single run → converts; `italic` stripped; id preserved;
   type/props correct.
2. Italic runs split by an unstyled punctuation-only run (`", "`) →
   converts (D4).
3. Trailing whitespace-only run → converts.
4. Paragraph with one upright word among italics → does NOT convert.
5. Mixed inline italics (`partly *italic*`) → does NOT convert (brief B).
6. Italic + bold runs (`<em><strong>` pseudo-heading) → converts, `bold`
   preserved, flagged (<12 words).
7. fnRef marker run amid italics → converts; fnRef run untouched by
   `strip_italic`.
8. Fully italic link (link whose content runs are italic) → converts;
   italic stripped inside the link.
9. Empty paragraph / whitespace-only italic paragraph → does NOT convert
   (D4's word requirement).
10. Heading with fully italic content, quote block, bulletListItem with
    italic content → NOT converted (D5).
11. Existing forgeNarrative block → passes through unchanged; running
    `convert_full_italic_paragraphs` twice equals running it once
    (idempotence).
12. `add_italic(strip_italic(x))` restores italic on all word runs; fnRef
    runs never gain italic.
13. Report entries: word count, 90-char preview with ellipsis, flag
    boundary (11 words flagged, 12 words not).
14. Label resolution: no setting → ""; setting `"From the author"` →
    inherited; meta key `""` present → `""` (explicit none); meta key
    `"Reflection"` → override (D9).

### Acceptance

`uv run pytest backend/tests/test_narrative.py` green; `make check` green;
nothing else changed.

---

## Milestone M2 — HTML renderer + parser + round-trip fixtures

### Files

| File | Change |
|---|---|
| `backend/templates/page.html.j2` | `:root` tokens (D2), narrative CSS block, `narrative` case in the article loop, `narrative_label` context var |
| `backend/notebook_forge/renderer.py` | `FORGE_NARRATIVE` import; `build_body` narrative entries; `_merge_narrative`; `render_document` passes `narrative_label` |
| `backend/notebook_forge/parser.py` | `div.narrative` branch in `parse_article` |
| `backend/tests/fixtures/narrative_panel.html` | **new** fixture: one panel, one `<p>` |
| `backend/tests/fixtures/narrative_merged.html` | **new** fixture: one panel, three `<p>` (merged case) |
| `backend/tests/test_renderer.py`, `backend/tests/test_parser.py` | new cases + fixtures auto-picked by the idempotency gate |

### page.html.j2

`:root` (after `--rule`):

```css
--narr-bg:#f1eada;
--narr-border:#b8a580;
```

CSS, inserted directly after the footnote block (`aside.footnote p{…}`)
with this comment (the contrast contract, kept next to the code):

```css
/* ---- Narrative (author's reflective voice) ---- */
/* Body-size upright serif in a warm tinted panel. Deliberately distinct
   from aside.footnote on all three axes: SIZE (1em vs .86rem), TINT
   (warm --narr-bg panel vs untinted), MARKER (none vs numbered fn-num). */
div.narrative{
  background:var(--narr-bg);
  border-left:3px solid var(--narr-border);
  border-radius:0 10px 10px 0;
  padding:1.05rem 1.25rem;
  margin:1.6rem 0;
}
div.narrative p{margin:0 0 1.05rem;}
div.narrative p:last-child{margin-bottom:0;}
div.narrative .narrative-label{
  font-family:ui-sans-serif,system-ui,"Helvetica Neue",Arial,sans-serif;
  font-variant-caps:all-small-caps;
  letter-spacing:.14em;
  font-size:.78rem;
  font-weight:600;
  color:var(--ink-soft);
  margin:0 0 .55rem;
}
```

Article loop, new case after `footnote`:

```jinja
{% elif block.kind == 'narrative' %}
  <div class="narrative">
    {% if narrative_label %}<p class="narrative-label">{{ narrative_label }}</p>{% endif %}
    {% for para in block.paragraphs %}
    <p>{{ para }}</p>
    {% endfor %}
  </div>
```

(`para` items are `Markup` — already-escaped inline HTML, same trust model
as `block.text_html|safe` elsewhere.)

### renderer.py

In `build_body`, after the `paragraph` branch:

```python
elif btype == FORGE_NARRATIVE:
    text = inline_text(block.get("content"))
    if not text.strip():
        continue          # blank narrative blocks are skipped like blank paragraphs
    body.append({
        "kind": "narrative",
        "text": text,
        "paragraphs": [Markup(inline_html(block.get("content")))],
    })
```

Narrative does NOT take the `lead` flag (drop-cap belongs to ordinary
prose; if a doc opens with narrative, the first ordinary paragraph still
gets the drop cap — by design).

After `body = _group_list_items(body)` add `body = _merge_narrative(body)`:

```python
def _merge_narrative(body):
    """Consecutive narrative entries collapse into ONE panel with
    paragraph breaks inside — never stacked boxes (locked decision A)."""
    out: list[dict[str, Any]] = []
    for entry in body:
        if entry["kind"] == "narrative" and out and out[-1]["kind"] == "narrative":
            out[-1]["paragraphs"].extend(entry["paragraphs"])
        else:
            out.append(entry)
    return out
```

`render_document`: add `narrative_label=meta.get("narrative_label", "")`
to the `tpl.render(...)` kwargs. (Callers inject the *resolved* label into
their meta copy — M3. `render_document` itself stays session-free.)

### parser.py

In `parse_article`, **before** the generic `div/section/article` recursion
branch:

```python
elif name == "div" and "narrative" in classes:
    for p in el.find_all("p", recursive=False):
        if "narrative-label" in (p.get("class") or []):
            continue  # derived furniture (workspace/doc label), not content
        blocks.append(make_block("forgeNarrative", content=parse_inline(p)))
```

One panel with N paragraphs → N consecutive forgeNarrative blocks; the
renderer's `_merge_narrative` reassembles them (D7).

### Fixtures

`narrative_panel.html`:

```html
<p>An ordinary paragraph before.</p>
<div class="narrative">
<p>Looking back on those years I wonder how we managed at all.</p>
</div>
<p>An ordinary paragraph after.</p>
```

`narrative_merged.html`: same shape with three `<p>` inside one panel and
a footnote aside after the panel (`<aside class="footnote"><span
class="fn-num">7</span>A note.</aside>`) so the fixture also locks the
panel/footnote adjacency.

### Tests

- `test_parser.py`: `parse_fragment(narrative_panel)` yields
  `paragraph, forgeNarrative, paragraph`; merged fixture yields three
  consecutive forgeNarrative blocks + forgeFootnote; label `<p>` skipped
  (add a label line to a fragment inline in the test).
- `test_renderer.py`: the existing parametrised
  `test_fragment_round_trip_is_idempotent` picks the two new fixtures up
  automatically (verify the fixture list is glob-driven; if it is an
  explicit list, append both). Add `test_narrative_merge`: three
  consecutive forgeNarrative blocks render exactly **one**
  `div.narrative` with three `<p>`; blocks split by a forgeFootnote render
  two panels. Add `test_narrative_label_rendered`: meta
  `narrative_label="From the author"` → `p.narrative-label` present with
  the text, absent when the meta key is empty/missing.
- **Contrast proof (brief A, mandatory)** in `test_renderer.py`:
  `test_narrative_footnote_contrast` renders a synthetic document whose
  blocks are [paragraph, forgeNarrative, forgeFootnote] and
  (a) asserts the narrative panel markup has no `fn-num`/marker and the
  footnote aside has one; (b) asserts over the template CSS text:
  `div.narrative{` block contains `background:var(--narr-bg)` and
  `border-left:3px solid var(--narr-border)` and sets no `font-size`
  (body-size), while `aside.footnote{` contains `font-size:.86rem` and no
  `background`; (c) **writes the rendered page to
  `reports/narrative_contrast.html`** — the committed side-by-side visual
  fixture for human eyes.

### Acceptance

`make check` green; `reports/narrative_contrast.html` exists, opens in a
browser showing the warm body-size panel directly above the small grey
numbered footnote.

---

## Milestone M3 — Label setting, per-doc override, dirty fold

### Files

| File | Change |
|---|---|
| `backend/notebook_forge/api.py` | `narrative` section in `GET /api/settings`; `PUT /api/settings/narrative` |
| `backend/notebook_forge/services.py` | `effective_content_hash` narrative fold (D11) |
| `backend/notebook_forge/publish/service.py` | resolve label into the meta copy in `build_bundle` |
| `backend/notebook_forge/importer.py` | same resolution in `roundtrip_document` |
| `frontend/src/api.ts` | `settings()` type + `saveNarrativeSettings` |
| `frontend/src/views/Settings.tsx` | "Narrative voice" section |
| `frontend/src/views/Editor.tsx` | MetaBar override control |
| `backend/tests/test_publish.py` (or new `test_narrative_label.py`) | label + dirty tests |

### Backend

- `GET /api/settings`: add `"narrative": {"label": narrative_label_setting(session)}`.
- `PUT /api/settings/narrative`, body `class NarrativeSettingsBody(BaseModel): label: str = ""` —
  upsert Setting `narrative` with `{"label": body.label.strip()}` (mirror
  `save_polish_settings`).
- `services.effective_content_hash`: restructure to build one meta copy:

```python
def effective_content_hash(session: Session, doc: Document) -> str:
    from .blocks import FORGE_NARRATIVE
    meta = dict(doc.meta)
    if doc.kind == "homepage":
        from .homepage import group_listing_fingerprint
        meta["__group_listing__"] = group_listing_fingerprint(session, doc.blocks)
    if any(b.get("type") == FORGE_NARRATIVE for b in doc.blocks):
        from .narrative import effective_narrative_label
        meta["__narrative_label__"] = effective_narrative_label(session, doc)
    return content_hash(doc.blocks, meta)
```

- `publish/service.py` `build_bundle`, where `meta = dict(doc.meta)`
  already exists (~line 74): add

```python
from ..narrative import effective_narrative_label
meta["narrative_label"] = effective_narrative_label(session, doc)
```

- `importer.roundtrip_document`: render with
  `meta = {**doc.meta, "narrative_label": effective_narrative_label(session, doc)}`.

### Frontend

- `api.ts`: extend the settings response type with
  `narrative: { label: string }`; add
  `saveNarrativeSettings(body: { label: string })` → `PUT /api/settings/narrative`.
- `Settings.tsx`: new section between "Text polish" and "Connections" —
  head **"Narrative voice"**, copy: "Optional small-caps label above each
  narrative panel on published pages (e.g. 'From the author'). Leave blank
  for none — the recommended default. Per-document override lives in the
  document's meta bar." One `settings-row` labelled input + save button
  with state span, exactly the polish-section pattern.
- `Editor.tsx` MetaBar: after the ToC select, add a `meta-narrative`
  control rendered **only when** `doc.blocks.some(b => b.type ===
  'forgeNarrative')` (keeps the bar clean for the five unaffected
  memoirs): a checkbox "Narrative label override" plus a text input
  enabled only when checked. State init: checked iff
  `'narrative_label' in doc.meta`; value `String(meta.narrative_label ?? '')`.
  `save()`: when checked set `updated.narrative_label = value` (may be
  `""` = explicit none); when unchecked `delete updated.narrative_label`
  (inherit). Include both in the `dirty` computation.

### Tests

1. PUT/GET settings round-trip; label trimmed.
2. Dirty fold: doc with narrative blocks, snapshot+mark published →
   changing the workspace label makes `is_dirty` true; doc **without**
   narrative blocks stays clean (D11 both directions).
3. Per-doc override `""` beats a non-empty workspace label (renders no
   label via `build_bundle` html).
4. `build_bundle` html contains `narrative-label` text when workspace
   label set and doc has narrative blocks.

### Acceptance

`make check` green. Manual: Settings shows the new section; a doc with
narrative blocks shows the MetaBar override; one without doesn't.

---

## Milestone M4 — Ingest paths (DOCX, PDF, house-style HTML)

### Files

| File | Change |
|---|---|
| `backend/notebook_forge/ingestion.py` | conversion post-pass in `_extract_blocks`; report fields through `ingest_document` / `reingest_document` |
| `backend/notebook_forge/importer.py` | post-pass in `import_document` + coverage notes |
| `backend/notebook_forge/api.py` | pass-through of the new fields in `/api/ingest` & `/api/documents/{slug}/reingest` responses (verify — likely automatic since the dicts are returned verbatim) |
| `backend/tests/test_ingestion.py`, `backend/tests/test_importer.py` | new cases |

### ingestion.py

`_extract_blocks` grows a 5th tuple element:

```python
blocks = draft_to_blocks(draft, session, workspace, media)
blocks, conversions = convert_full_italic_paragraphs(blocks)
return draft, blocks, date_stem, date_display, conversions
```

Update its three call sites (`ingest_document`, `reingest_document`, and
`reimport.dry_run` does NOT call it — it calls `_run_extraction`, no
change). `ingest_document` and `reingest_document` add to their returned
dicts:

```python
"narrative_conversions": len(conversions),
"narrative_flagged": [c["preview"] for c in conversions if c["flagged"]],
```

and append to the change-log summary when `conversions`:
`f", {len(conversions)} narrative passage(s) converted"` with the flagged
previews in the change `detail` (D17).

### importer.py

In `import_document` after `parse_page(html)`:

```python
page.blocks, conversions = convert_full_italic_paragraphs(page.blocks)
for c in conversions:
    if c["flagged"]:
        cov.notes.append(f"narrative <12 words, review: “{c['preview']}”")
if conversions:
    cov.notes.append(f"{len(conversions)} full-italic paragraph(s) → forgeNarrative")
```

(Coverage notes flow into reports/import-coverage.md via the existing
writer — no writer changes.)

### Tests

1. DOCX path: a `TextBlock(text="*Entirely italic reflection across many words indeed*")`
   through `draft_to_blocks`+post-pass → forgeNarrative, upright runs.
   (Build the draft directly; do not require a real .docx — follow the
   existing test_ingestion fixtures' style.)
2. PDF-style emphasis `*italic*` mid-sentence → stays paragraph.
3. `***bold italic***` whole paragraph → converts, bold kept, flagged when
   short.
4. House-style import: a fixture page (extend
   `backend/tests/fixtures/full_page_in_the_navy.html`? **No** — keep the
   real-corpus fixture pristine; add a new minimal full-page fixture
   `full_page_narrative.html` with masthead + one `<p><em>…</em></p>` of
   ≥12 words and one of <12) → imported doc has forgeNarrative blocks;
   coverage notes contain the flag line.
5. Ingest response dict carries `narrative_conversions` /
   `narrative_flagged`.
6. Re-ingest (`reingest_document`) on a doc whose source produces a
   full-italic paragraph → converted; figure carry-over untouched.

### Acceptance

`make check` green. The conversion is now unreachable ONLY via stored
documents — that is M7's job.

---

## Milestone M5 — Editor: block, slash command, convert menu

### Files

| File | Change |
|---|---|
| `frontend/src/forge/ForgeNarrativeView.tsx` | **new** presentational wrapper |
| `frontend/src/forge/narrative.ts` | **new** run-style helpers (mirrors backend D3) |
| `frontend/src/forge/schema.tsx` | `forgeNarrativeSpec`, register in `forgeSchema`, `narrativeSlashItem` |
| `frontend/src/views/Editor.tsx` | slash item in BOTH menu branches; `SideMenuController` with convert items |
| `frontend/src/index.css` | `:root` tokens + `.forge-narrative` styles |
| `frontend/src/test/forge-narrative.test.tsx` | **new** |
| `frontend/src/test/narrative-helpers.test.ts` | **new** |

### schema.tsx

```tsx
export const forgeNarrativeSpec = createReactBlockSpec(
  { type: 'forgeNarrative', propSchema: {}, content: 'inline' },
  {
    render: ({ contentRef }) => (
      <div className="forge-narrative" data-testid="forge-narrative">
        <p className="forge-narrative-text" ref={contentRef} />
      </div>
    ),
  },
)
```

Register `forgeNarrative: forgeNarrativeSpec()` in `forgeSchema.blockSpecs`.
No label in the editor (D10).

```tsx
export function narrativeSlashItem(editor: any) {
  return {
    title: 'Narrative',
    aliases: ['narrative', 'reflection', 'voice'],
    group: 'Forge',
    subtext: "Author's reflective voice — tinted panel",
    icon: <i className="ti ti-feather" />,
    onItemClick: () => insertOrUpdateBlockForSlashMenu(editor, { type: 'forgeNarrative' }),
  }
}
```

> **Verify-imports-only risk note:** `createReactBlockSpec` with
> `content:'inline'` and `SideMenuController`/`SideMenu`/`DragHandleMenu`
> are documented BlockNote 0.51 APIs but unused in this repo so far. Before
> writing components, check the actual exports in
> `frontend/node_modules/@blocknote/react/dist` and adapt names only if
> they differ; the behaviourial spec here is binding.

### narrative.ts (pure, unit-tested)

```ts
// Mirrors backend narrative.strip_italic / add_italic (decision D3).
export function stripItalic(content: InlineContent[]): InlineContent[]
export function addItalic(content: InlineContent[]): InlineContent[]   // skips fnRef-styled runs
```

(Operate on the plain JSON shape — text runs `{type:'text', text, styles}`
and links recursively; type loosely as `any[]` if BlockNote's generic
types fight back, with a comment.)

### Editor.tsx

- Both `SuggestionMenuController` branches gain `narrativeSlashItem(editor)`
  (homepage: appended after `docGroupSlashItem`; non-homepage: appended to
  `all`).
- Inside `<BlockNoteView>`, alongside the suggestion controllers, add:

```tsx
<SideMenuController
  sideMenu={(props) => (
    <SideMenu {...props} dragHandleMenu={(menuProps) => (
      <DragHandleMenu {...menuProps}>
        <RemoveBlockItem {...menuProps}>Delete</RemoveBlockItem>
        <BlockColorsItem {...menuProps}>Colors</BlockColorsItem>
        <ConvertNarrativeItem {...menuProps} editor={editor} />
      </DragHandleMenu>
    )} />
  )}
/>
```

`ConvertNarrativeItem` (in Editor.tsx or a small
`frontend/src/forge/ConvertNarrativeItem.tsx` — Sonnet's choice, one file):
uses `useComponentsContext()!.Generic.Menu.Item`; reads
`menuProps.block`:
  - `block.type === 'paragraph'` → item "Convert to narrative", onClick:
    `editor.updateBlock(block, { type: 'forgeNarrative', content: stripItalic(block.content) })`
  - `block.type === 'forgeNarrative'` → item "Convert to paragraph"
    (the undo path for false-positive conversions), onClick:
    `editor.updateBlock(block, { type: 'paragraph', content: addItalic(block.content) })`
  - any other type → render nothing (`null`).

### index.css

`:root` additions: `--narrative-bg: #f1eada; --narrative-border: #b8a580;`

After the `.forge-footnote` rules:

```css
/* ---- forgeNarrative block ---- */
/* Warm tinted panel, full editor body size, no marker — the in-editor
   twin of div.narrative on the published page (contrast with
   .forge-footnote: 13px, grey, marker input). */
.forge-narrative {
  background: var(--narrative-bg);
  border-left: 3px solid var(--narrative-border);
  border-radius: 0 8px 8px 0;
  padding: 10px 14px;
  margin: 6px 0;
  width: 100%;
}
.forge-narrative-text { margin: 0; }
```

### Tests

`forge-narrative.test.tsx`:
1. `forgeSchema.blockSpecs` includes `forgeNarrative` (schema smoke, like
   the existing forge-blocks test).
2. View renders `data-testid="forge-narrative"` with class
   `forge-narrative` and an inner `.forge-narrative-text`.

`narrative-helpers.test.ts`:
3. `stripItalic` removes italic from text and link-inner runs, leaves
   other styles.
4. `addItalic` italicises word runs, skips fnRef runs;
   `addItalic(stripItalic(x))` restores an all-italic paragraph.

### Acceptance

`make check` green (frontend tests included). **Manual (preview tools)**:
open Junior in the editor — `/narrative` inserts a tinted panel; typing
works like a paragraph; drag-handle menu on a paragraph shows "Convert to
narrative", on a narrative block shows "Convert to paragraph"; converting
a hand-italicised paragraph strips the italics; converting back restores
them; autosave fires; zero console errors. Enter at the end of a narrative
block may create a paragraph (BlockNote default) — acceptable, do not
fight the keymap.

---

## Milestone M6 — Safe edition (Drive), homepage rendering, polish

### Files

| File | Change |
|---|---|
| `backend/notebook_forge/safe_edition.py` | narrative blockquote case (D8) |
| `backend/notebook_forge/homepage.py` | `narrative` entry kind in `homepage_body` + merge |
| `backend/templates/index.html.j2` | `:root` tokens, narrative CSS, `narrative` case in the `body_entries` loop |
| `backend/notebook_forge/polish/textmap.py` | `forgeNarrative` in `POLISHABLE` (D16) |
| `backend/tests/test_safe_edition.py`, `test_homepage.py`, `test_polish.py` | new cases |

### safe_edition.py

In `render_safe_markdown`'s block loop, add **before** the paragraph
branch, with a `prev_narrative` flag initialised `False` beside `fig_n`:

```python
elif btype == FORGE_NARRATIVE:
    text = inline_md(block.get("content")).strip()
    if text:
        if prev_narrative and lines and lines[-1] == "":
            lines[-1] = ">"           # merge: paragraph break INSIDE the quote
        lines += [f"> {text}", ""]
        prev_narrative = True
    continue
```

and set `prev_narrative = False` at the bottom of every other branch's
iteration (simplest: set `prev_narrative = False` at the TOP of the loop
body, and have only the narrative branch set it True before `continue`).
Result for two consecutive narrative blocks:

```
> First reflective paragraph.
>
> Second reflective paragraph.
```

Upright (inline_md only emits `*…*` for runs still styled italic — and
conversion stripped those). No marker, no label (D8: footnotes keep their
bold `[N]`; body text is unindented — three-way distinct within
Markdown→Doc's vocabulary; colour is not expressible there, decided after
reading the real markdown-upload pipeline).

### homepage.py

In `homepage_body`'s block loop add:

```python
elif btype == FORGE_NARRATIVE:
    rendered = inline_html(block.get("content") or [])
    if rendered.strip():
        body_entries.append({"kind": "narrative", "paragraphs": [rendered]})
```

After the loop, merge consecutive narrative entries (same algorithm as
renderer `_merge_narrative` — import it from `renderer` to avoid a copy;
it is already shape-compatible since both use `kind`/`paragraphs`).

### index.html.j2

- `:root`: add the two `--narr-*` tokens (D2).
- Style block: copy the `div.narrative` rules from page.html.j2 **minus**
  the `.narrative-label` rule (labels don't render on the homepage, D9).
- `body_entries` loop, after the `dedication` case:

```jinja
{% elif e.kind == 'narrative' %}<div class="narrative">{% for p in e.paragraphs %}<p>{{ p|safe }}</p>{% endfor %}</div>
```

### polish/textmap.py

`POLISHABLE = ("paragraph", "heading", "quote", "bulletListItem",
"numberedListItem", "forgeNarrative")` — narrative serialises as kind `p`
(the existing else-branch) and polish writes content runs back by index,
which is type-agnostic. Verify `blocks_to_textmap`/apply round-trip with a
test before trusting this paragraph.

### Tests

1. Safe edition: [paragraph, narrative, narrative, footnote] → markdown
   has one `>`-quoted region with a `>` separator line, footnote line
   keeps `> **[7]**`, no `*` wrapping in the narrative, **no label text
   even when the workspace label is set** (call `render_safe_markdown`
   directly with meta containing `narrative_label` — it must be ignored).
2. Drive publish (MockDriveClient): bundle.safe_md contains the unmarked
   blockquote — proves the Doc representation end-to-end at request level.
3. Homepage: doc with two consecutive narrative blocks between intro
   paragraphs → `homepage_body` yields ONE narrative entry with two
   paragraphs; rendered index HTML contains one `div.narrative`.
4. Polish: a forgeNarrative block's typo is polishable
   (MockRunner-style, following test_polish.py patterns); fidelity guard
   still applies.

### Acceptance

`make check` green. Safe-edition output for a synthetic doc eyeballed in
the test fixture (assert exact markdown lines, not just substrings).

---

## Milestone M7 — Migration of the stored library (own milestone)

### Files

| File | Change |
|---|---|
| `backend/notebook_forge/narrative_migration.py` | **new** |
| `backend/notebook_forge/cli.py` | `narrative-migrate` subcommand |
| `backend/tests/test_narrative_migration.py` | **new** |

### narrative_migration.py

```python
"""One-time migration: full-italic paragraph blocks → forgeNarrative
(rule B via narrative.convert_full_italic_paragraphs).

Two phases (locked decision D): a DRY RUN that writes
reports/narrative_migration.md, then an APPLY that snapshots every
affected document first. Guarded by the 'narrative_migration' Setting so
a casual re-run cannot re-convert paragraphs an operator deliberately
converted back in the editor (--force overrides). Homepage excluded (D13).
"""

MARKER_KEY = "narrative_migration"

def scan(session) -> list[dict]:
    # for each services.list_documents(session) doc with kind != "homepage":
    #   _, conversions = convert_full_italic_paragraphs(doc.blocks)
    #   → {"slug", "title", "count": len(conversions), "conversions": [...]}
    # include zero-count docs (the report shows full coverage)

def already_applied(session) -> dict | None   # Setting row value or None

def apply(session) -> list[dict]:
    # per doc from scan() with count > 0:
    #   new_blocks, conversions = convert_full_italic_paragraphs(doc.blocks)
    #   services.snapshot_document(session, doc, note="before narrative migration")
    #   services.save_blocks(session, doc, new_blocks,
    #       summary=f"narrative migration: {len(conversions)} paragraph(s) converted")
    # then upsert Setting MARKER_KEY {"applied_at": utcnow().isoformat(),
    #   "converted": {slug: count}}
    # returns the scan rows actually applied

def write_report(reports_dir: Path, rows: list[dict], mode: str) -> None:
    # reports/narrative_migration.md:
    #   header (mode, timestamp, totals), then per document:
    #   ## {slug} — {count} conversion(s)
    #   - [FLAG <12 words] “{preview}” ({words} words)
    #   zero-count docs listed under "No conversions: …" one line
    #   footer: rollback note — "every applied document has a snapshot
    #   'before narrative migration'; restore it from the editor's
    #   Snapshots panel or POST /api/documents/{slug}/rollback"
```

Dirty marking needs no code: `save_blocks` changes the content hash, so
every affected document goes dirty for all its targets (verified by test).

### cli.py

Subparser `narrative-migrate` with `--dry-run` / `--apply` (one required,
mutually exclusive), `--force`, `--workspace` (default `workspace_path()`),
`--reports` (default repo `reports/`). Follow `_cmd_reimport`'s structure:
bootstrap workspace, sessionmaker, print one line per document
(`{slug}: {count} conversion(s), {flagged} flagged`), write the report in
BOTH modes (the apply-mode report is the durable record of what changed).
`--apply` when `already_applied` and not `--force` → print the marker's
`applied_at` and exit 1 without touching anything. Commit the session once
after `apply`.

### Tests (in-memory DB, fixtures via services.create_document)

1. Dry run converts nothing (blocks unchanged, no snapshots, no marker)
   and reports counts + flags correctly.
2. Apply converts, snapshots first (snapshot blocks contain the original
   italic paragraph), marks dirty for a seeded target, writes marker.
3. Idempotence: second apply with `--force` converts 0 (all already
   forgeNarrative); without `--force` refuses (exit path) when marker set.
4. Operator-undo protection: after apply, convert one block back to an
   italic paragraph (simulating the editor remedy), re-run apply WITHOUT
   force → refused; with `--force` → it reconverts (documented behaviour).
5. Homepage doc with a hypothetical full-italic paragraph → untouched.
6. Report file: per-doc sections, flag lines, rollback footer, zero-count
   listing.
7. A doc already containing forgeNarrative blocks plus one new italic
   paragraph → only the paragraph converts (brief edge case).

### Acceptance

`make check` green. **Operator step (Sonnet runs it, against a COPY of the
real workspace via `NOTEBOOK_FORGE_WORKSPACE` — never the live one until
the dry-run report is reviewed):**
`uv run python -m notebook_forge.cli narrative-migrate --dry-run` →
inspect `reports/narrative_migration.md`; expected: ~16 conversions in
part-2, ~6 in part-4 (incl. 2 flagged pseudo-headings + any short flagged
lines), 0 elsewhere. Then `--apply` on the same copy, open part-2 in the
editor and verify panels render; push to **local-folder only** and eyeball
the page. Applying to the real workspace is the operator's call —
record it as an operator note, do not do it.

---

## Milestone M8 — Round-trip harness, hardening, docs

### Files

| File | Change |
|---|---|
| `backend/tests/test_importer.py` | self-idempotence gate (D15) |
| `backend/notebook_forge/importer.py` | roundtrip report note for converted docs |
| `reports/roundtrip.md` | regenerated/annotated expectations (operator-reviewed) |
| `README.md` | Narrative blocks section |
| `SPRINT_REPORT.md` | sprint addendum |
| `backend/tests/test_*` | edge-case sweep below |

### Harness changes (D15)

1. `test_importer.py` new test `test_narrative_roundtrip_idempotent`:
   using the `full_page_narrative.html` fixture from M4 —
   `r1 = render(parse+convert)`; `p2 = parse_page(r1)` must contain
   forgeNarrative blocks equal (ids stripped) to the originals,
   **including the merged-panel case splitting back into consecutive
   blocks**; `r2 = render(p2.blocks)` must be DOM-equal to `r1` at 100%
   (`domcompare.compare(...).similarity == 1.0`).
2. `roundtrip_document` already re-renders from stored blocks; after the
   M7 migration the stored blocks contain narrative, while the published
   files don't yet — add to `write_roundtrip_report` a per-doc note when
   the doc contains forgeNarrative blocks: "contains N narrative panels —
   published page predates the feature; divergence on those paragraphs is
   intentional until republished". Do NOT lower the numeric gate in code;
   the gate lives in tests, which use fixtures, not the live corpus.
3. Confirm `test_renderer.test_full_page_render_matches_published_dom`
   still passes — its fixture (in-the-navy) has zero italic paragraphs
   (verified in §1), so conversion is a no-op there. If any other fixture
   contains a full-italic paragraph, the parse-only path (no conversion)
   keeps it a paragraph — the M3 gate is unaffected by design (D6).

### Edge-case test sweep (one test each, named for the case)

- Empty italic paragraph (`<p><em> </em></p>`) → parses to paragraph,
  never converts, renderer drops it (existing blank-skip).
- Italics inside list items → not converted (already in M1 tests; here:
  end-to-end through `parse_fragment` + convert pass).
- Italic block quotation in paragraph form → converts; assert the change
  is reversible via `add_italic` (the documented editor remedy).
- Document already containing forgeNarrative + migration → idempotent
  (M7 test 7 covers; reference it, don't duplicate).
- Narrative block as the document's first block → no `lead` drop-cap on
  the panel; first ordinary paragraph still gets `lead`.
- fnRef marker inside a narrative paragraph survives conversion, renders
  as `sup.fn-ref` inside the panel, and the adjacent forgeFootnote splits
  the panel (two `div.narrative`) — the full co-location story.
- FTS: narrative text appears in `plain_text` output (generic branch) —
  one assertion in test_data_layer or test_narrative.

### Docs

- README: short "Narrative blocks" section — what converts (rule B in one
  sentence), the editor remedy, the label setting, the migration command
  pair, the contrast fixture path.
- SPRINT_REPORT addendum: milestones, gate table, operator notes:
  1. run `narrative-migrate --dry-run`, review
     `reports/narrative_migration.md` (expect part-2 ≈16, part-4 ≈6,
     flagged pseudo-headings are likely keep-as-narrative intro lines —
     convert back in the editor if not);
  2. `--apply`, review part-2/part-4 in the editor, push to local-folder,
     eyeball, then push live at your discretion;
  3. the two memoirs will show dirty for github-pages and drive after
     apply — that is the feature working;
  4. optional: set a workspace narrative label in Settings (e.g. "From
     the author") — note it marks only narrative-bearing docs dirty.

### Acceptance (whole feature)

`make check` fully green (target: every existing test plus ~45 new
backend / ~8 new frontend). `reports/narrative_contrast.html` and
`reports/narrative_migration.md` (dry-run against the workspace copy)
committed. Manual editor verification from M5 done with preview tools and
zero console errors.

---

## Risks

| Risk | Mitigation |
|---|---|
| BlockNote 0.51 API drift for `content:'inline'` custom blocks or `SideMenuController`/`DragHandleMenu` | Verify-imports-only note in M5; behaviour spec is binding, names may adapt. The two existing custom blocks prove the spec factory; inline content + side menu are the only new surfaces. |
| Rule B false positives (italic quotations, pseudo-headings) | By design (brief): convert + flag <12 words + editor convert-back; migration is marker-guarded so the operator's manual reverts are never silently re-applied (D13). |
| Round-trip similarity vs live site drops for part-2/part-4 after migration | Intentional (D15): annotated in roundtrip report; hard gate moves to self-idempotence; unaffected five memoirs keep ≥99%. |
| Workspace-label change silently not propagating to published pages | D11 hash fold marks exactly the narrative-bearing docs dirty; covered by tests both directions. |
| Editor convert leaves runs with stale styles after `updateBlock` type change | Helpers pass explicit `content`; unit tests on stripItalic/addItalic; manual M5 check. |
| `_extract_blocks` signature change breaks a missed caller | Only `ingest_document`/`reingest_document` call it (grep verified); reimport reaches it through `reingest_document`. Grep again before committing M4. |
| Safe-edition `prev_narrative` state bug producing two stacked quotes | Exact-markdown-line assertions in M6 test 1, including the `>` separator line. |
| Migration applied twice via `--force` after operator reverts | Documented loudly in the report footer and M7 test 4; `--force` is the operator saying "I know". |

## Operator notes (post-merge, for Chris)

1. Nothing converts until you run
   `uv run python -m notebook_forge.cli narrative-migrate --dry-run`
   (safe, report-only) and then `--apply`. Review the report between the
   two — the <12-word flags are the two bold pseudo-heading lines and any
   short passages; if one is wrong, apply anyway and use "Convert to
   paragraph" from the block's drag-handle menu in the editor.
2. After apply, part-2 and part-4 show dirty everywhere — push
   local-folder first, eyeball, then github-pages and drive.
3. The label is off by default. Settings → Narrative voice to set one
   site-wide; per-document override in the doc's meta bar (only visible
   on docs that contain narrative blocks).
4. `reports/narrative_contrast.html` is the side-by-side footnote/narrative
   proof — open it if you ever doubt the styling.

---

## Kickoff prompt for Sonnet

Copy-paste exactly:

> Implement the plan in `docs/PLAN_narrative_blocks.md` end to end, in
> milestone order M1→M8. The plan is binding: every design decision is
> already made in its §2 "Locked decisions" table and the per-milestone
> specs — do not redesign, substitute libraries, or skip the listed tests.
> Work on a feature branch off `main`. Before starting, read
> `SPRINT_REPORT.md`, `backend/notebook_forge/{blocks,parser,renderer,services,ingestion,importer,safe_edition,cli}.py`,
> `backend/notebook_forge/polish/textmap.py`,
> `backend/templates/{page,index}.html.j2`,
> `frontend/src/forge/schema.tsx`, `frontend/src/views/{Editor,Settings}.tsx`
> and `frontend/src/index.css` so the plan's references are grounded.
> Commit at every milestone gate with conventional commits, keeping
> `make check` green at each gate; if a gate fails after 3 distinct fix
> attempts, record the failure honestly in the commit and continue.
> Hard guardrails from `BUILD_PLAN.md` §2 still apply: never push to any
> repo except origin, never run `git add -A`, never touch
> `/Users/cs/ClaudeCode/MemoirForge` or any family-history clone
> (vendor-readonly is read-only), no live publishing to the real
> github-pages or drive targets during verification — use a copied
> workspace (`NOTEBOOK_FORGE_WORKSPACE`) and the local-folder target for
> all live checks, including the M7 migration dry-run AND apply, which
> must both run against the copy only (applying to the real workspace is
> the operator's call, recorded as an operator note). When all milestones
> pass, run the M5 and M7 manual verifications with the preview tools,
> append the sprint addendum + operator notes to `SPRINT_REPORT.md` as
> specified in M8, and push the branch.
