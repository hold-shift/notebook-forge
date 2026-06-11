"""PDF extraction via PyMuPDF.

Per spec §6 S2:
  - text blocks with page + bbox
  - embedded images with page + bbox so each can be tied to nearby text
  - caption detection: short text blocks at a smaller-than-body font
    size, positioned just below an image and horizontally aligned with
    it. Multi-line captions are stitched together when continuation
    blocks sit directly underneath the previous line.
"""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from .model import DocumentDraft, ImageRef, TextBlock

# Page-number heuristic: digits-only block in the bottom 10% of the page.
_PAGE_NUMBER_BAND_FRAC = 0.88     # y_top > page_height * this → candidate
_PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,4}\s*$")

# Footnote heuristic: short-line block in the bottom 35% of the page, font
# strictly smaller than the body mode, starting with "<digit><space>".
_FOOTNOTE_BAND_FRAC = 0.65        # y_top > page_height * this → candidate
_FOOTNOTE_SIZE_RATIO = 0.92       # block size < body * this
_FOOTNOTE_LEAD_RE = re.compile(r"^\s*(\d{1,2})\s+(.+)$", re.DOTALL)

# Bold-heading detection inside a block. PyMuPDF span flag bit 4 (decimal 16)
# = bold. A line counts as bold when ≥ 80% of its characters carry the flag.
# Headings are typically short — anything over ~100 chars is paragraph prose
# that happens to be bold (rare but possible) and shouldn't get promoted.
_BOLD_FLAG = 16
_BOLD_LINE_RATIO = 0.8
_HEADING_LINE_MAX_CHARS = 100

# Heading-LEVEL detection. In these memoirs the top-level section heading is
# bold, horizontally CENTRED, and either ALL-CAPS ("ARRINO") or a bare year
# ("1945") → h2; sub-headings are bold but LEFT-ALIGNED at the body margin
# ("The Coverleys") → h3. We tell centred from left-aligned by page geometry:
# a centred heading is indented well right of the body's left margin AND sits
# with roughly symmetric left/right margins. Tunables are fractions of the
# page width (calibrated on real memoir PDFs: centred indent ≈0.38, |Δmargin|
# ≈0.06; left-aligned indent ≈0, |Δmargin| ≈0.64).
_HEADING_CENTRE_MIN_INDENT = 0.12       # left edge ≥12% of page-width right of the body margin
_HEADING_CENTRE_MAX_MARGIN_DIFF = 0.22  # |left margin − right margin| ≤22% of page width
_YEAR_HEADING_RE = re.compile(
    r"^(?:1[89]|20)\d{2}(?:\s*[–—-]\s*(?:1[89]|20)\d{2})?$"
)


def _lift_h3_when_no_h2(body: list[dict]) -> None:
    """In-place safety net: if the whole document used only LEFT-aligned bold
    headings (so the level classifier produced h3s but no h2s), promote every
    h3 to h2 — with a single heading level there is no top-level "above" them
    to be a sub-head of. A document that DID have centred caps/year top-level
    heads keeps its two-level split untouched."""
    if any(b.get("kind") == "h2" for b in body):
        return
    for b in body:
        if b.get("kind") == "h3":
            b["kind"] = "h2"


def _is_year_heading(text: str) -> bool:
    """A bare year or year range — '1945', '1939–1945'. These are top-level
    section dividers despite carrying no upper-case letters, so they're exempt
    from the all-caps test."""
    return bool(_YEAR_HEADING_RE.match(text.strip().strip(".,;:")))


def _is_caps_heading(text: str) -> bool:
    """All-caps section label like 'ARRINO'. Requires ≥1 letter so a pure
    digit/punctuation line isn't treated as caps here (years are handled
    separately)."""
    return any(c.isalpha() for c in text) and text == text.upper()


def _bold_heading_level(
    text: str,
    bbox: tuple | None,
    page_width: float,
    page_left: float,
) -> str:
    """Classify a bold, short heading line as top-level ("h2") or
    sub-heading ("h3") from page geometry + casing.

      h2 — CENTRED and (ALL-CAPS or a year): "ARRINO", "1945".
      h3 — everything else: the LEFT-ALIGNED bold sub-headings ("The
           Coverleys").

    With no usable geometry (missing bbox / page width) we can't distinguish
    centred from left-aligned, so we fall back to the historical behaviour and
    treat the line as a top-level h2."""
    if not bbox or page_width <= 0:
        return "h2"
    x0, x1 = bbox[0], bbox[2]
    indent = x0 - page_left                     # right of the body's left margin?
    margin_diff = abs(x0 - (page_width - x1))   # symmetric left/right margins?
    centred = (
        indent >= page_width * _HEADING_CENTRE_MIN_INDENT
        and margin_diff <= page_width * _HEADING_CENTRE_MAX_MARGIN_DIFF
    )
    if centred and (_is_caps_heading(text) or _is_year_heading(text)):
        return "h2"
    return "h3"

# TOC heuristic: page whose first meaningful (post-page-number) block is one
# of these markers — almost always means a table-of-contents/index page that
# we don't want carried into the assembled body (our LoF + headings cover it).
_TOC_MARKERS = {"contents", "table of contents", "index"}


# When the rendered-on-page bbox aspect ratio differs from the raw image's
# aspect ratio by more than this (relative) amount, Word cropped the image —
# render the visible region from the page instead of pulling the raw XObject,
# so the figure the operator sees matches the figure the reader sees.
_CROP_ASPECT_TOLERANCE = 0.06
# DPI for rendered crops — keeps file sizes reasonable while staying sharp
# enough for the silhouette gen + reader-side display.
_CROP_RENDER_DPI = 180
# Two image XObjects are treated as tiles of the same photo when their edges
# share at most this many points of gap (or overlap) and their perpendicular
# extents overlap by more than _TILE_OVERLAP_MIN.
_TILE_EDGE_GAP = 3.0
_TILE_OVERLAP_MIN = 0.7


def extract_pdf(path: Path, session_media_dir: Path) -> DocumentDraft:
    path = path.resolve()
    session_media_dir.mkdir(parents=True, exist_ok=True)

    source_sha256 = _sha256_file(path)
    doc = fitz.open(str(path))

    body: list[dict] = []
    images_by_hash: dict[str, ImageRef] = {}
    detected_captions: dict[int, str] = {}
    footnotes_all: list[dict] = []
    order = 0

    sizes = _collect_font_sizes(doc)
    h1_size, h2_size = _heading_thresholds(sizes)
    body_size = _mode_size(sizes)
    # Caption font is anything materially smaller than the dominant body size.
    caption_size_max = body_size * 0.95 if body_size > 0 else 0.0
    footnote_size_max = body_size * _FOOTNOTE_SIZE_RATIO if body_size > 0 else 0.0

    metadata = doc.metadata or {}
    detected_title = (metadata.get("title") or "").strip()
    detected_author = (metadata.get("author") or "").strip()
    detected_title_size = 1e9 if detected_title else -1.0

    last_para_text = ""

    for page_idx, page in enumerate(doc):
        page_height = page.rect.height
        # 1) Gather image bounding boxes for this page first so we can run
        #    the caption-detection pass against them. Adjacent tiles that
        #    share an edge are merged into a single "photo" — Word PDFs
        #    frequently slice a tall or wide photo into multiple XObjects.
        page_images_raw: list[tuple[tuple[float, float, float, float], int, dict]] = []
        for img_info in page.get_image_info(xrefs=True) or []:
            xref = img_info.get("xref", 0)
            if not xref:
                continue
            bbox = tuple(img_info.get("bbox", (0, 0, 0, 0)))
            page_images_raw.append((bbox, xref, img_info))
        page_images = _group_image_tiles(page_images_raw)

        # 2) Walk text blocks and also collect lines independently — captions
        #    in two-column / wraparound layouts are LINES sitting in the
        #    image's column while body text wraps around at the same y in
        #    another column. Block-level scanning misses these because
        #    PyMuPDF lumps the whole column-pair into a single block.
        raw_text_blocks: list[dict] = []
        page_lines: list[dict] = []  # (bbox, text, size, block_idx, line_idx)
        for block_idx, block in enumerate(page.get_text("dict").get("blocks", [])):
            if block.get("type") != 0:
                continue
            sizes_in_block: list[float] = []
            block_pieces: list[str] = []
            kept_line_indexes: list[int] = []   # populated after caption pass
            block_line_records: list[dict] = []
            for line_idx, line in enumerate(block.get("lines", [])):
                line_pieces: list[str] = []
                line_sizes: list[float] = []
                line_bold_chars = 0
                line_total_chars = 0
                for span in line.get("spans", []):
                    span_text = span.get("text", "") or ""
                    line_pieces.append(span_text)
                    sz = float(span.get("size", 0) or 0)
                    if sz > 0:
                        line_sizes.append(sz)
                    span_chars = sum(1 for c in span_text if not c.isspace())
                    line_total_chars += span_chars
                    if int(span.get("flags", 0)) & _BOLD_FLAG:
                        line_bold_chars += span_chars
                line_text = "".join(line_pieces).strip()
                if not line_text:
                    block_line_records.append({"text": "", "bbox": line.get("bbox"), "size": 0, "bold": False})
                    continue
                if line_sizes:
                    rounded = [round(s * 2) / 2 for s in line_sizes]
                    line_size = max(set(rounded), key=rounded.count)
                else:
                    line_size = 0.0
                line_bold = (
                    line_total_chars > 0
                    and (line_bold_chars / line_total_chars) >= _BOLD_LINE_RATIO
                )
                block_line_records.append({
                    "text": line_text, "bbox": line.get("bbox", (0,0,0,0)),
                    "size": line_size, "bold": line_bold,
                })
                page_lines.append({
                    "bbox": line.get("bbox", (0,0,0,0)),
                    "text": line_text,
                    "size": line_size,
                    "block_idx": block_idx,
                    "line_idx": line_idx,
                })
                sizes_in_block.extend(line_sizes)

            if not any(rec["text"] for rec in block_line_records):
                continue
            # Representative size = mode of spans in the block.
            if sizes_in_block:
                rounded = [round(s * 2) / 2 for s in sizes_in_block]
                dom_size = max(set(rounded), key=rounded.count)
            else:
                dom_size = 0.0
            x0, y0, x1, y1 = block.get("bbox", (0, 0, 0, 0))
            joined_text = " ".join(rec["text"] for rec in block_line_records if rec["text"]).strip()
            # Drop page numbers — digits-only block in the bottom band.
            if (
                y0 > page_height * _PAGE_NUMBER_BAND_FRAC
                and _PAGE_NUMBER_RE.match(joined_text)
            ):
                continue
            raw_text_blocks.append({
                "bbox": (x0, y0, x1, y1),
                "text": joined_text,
                "size": dom_size,
                "block_idx": block_idx,
                "line_records": block_line_records,
            })

        # 2a-bis) Promote bold-short lines to heading blocks. Many PDFs (the
        #         Vietnam memoir is one) use Arial,Bold at body size for
        #         section heads inline with the body block, so the font-size
        #         heuristic alone misses them. We split each block at every
        #         bold-short line, marking the line as a heading (kind_hint=
        #         h2) and leaving the surrounding lines as ordinary
        #         paragraphs. This is what populates the auto-ToC.
        raw_text_blocks = _split_blocks_at_bold_headings(
            raw_text_blocks, body_size, page.rect.width,
        )

        # 2b) Lift footnotes off the bottom of the page before we hand the
        #     body off to paragraph emission. Works at the LINE level, not
        #     the block level: PyMuPDF often merges a whole column — body
        #     paragraph AND the footnote beneath it — into one block whose
        #     top sits high on the page, so a block-level "is the block in
        #     the bottom band?" test skips it and the footnote is buried.
        raw_text_blocks = _split_footnote_lines(
            raw_text_blocks, page_height, footnote_size_max,
            footnotes_all, page_idx,
        )

        # 2c) Skip TOC pages outright — the first remaining heading-style
        #     block is "CONTENTS" / "TABLE OF CONTENTS" / "INDEX". Our LoF
        #     + the doc's natural H2/H3 outline supersede it.
        if raw_text_blocks:
            first_text = raw_text_blocks[0]["text"].strip().lower()
            head_word = re.split(r"[\s—–\-]", first_text, 1)[0].strip()
            if first_text in _TOC_MARKERS or head_word in _TOC_MARKERS:
                raw_text_blocks = []
                page_lines = []

        # 3) Resolve image extraction + caption detection together.
        consumed_text_ids: set[int] = set()
        consumed_line_keys: set[tuple[int, int]] = set()
        page_items: list[tuple[float, dict]] = []
        for bbox, xrefs in page_images:
            if len(xrefs) == 1:
                ext, data, h = _extract_image_respecting_crop(doc, page, xrefs[0], bbox)
            else:
                # Multi-tile group: always render the combined visible region.
                ext, data, h = _render_tile_group(page, bbox)
            xref = xrefs[0]
            caption_text, used_ids = _find_caption(
                bbox, raw_text_blocks, consumed_text_ids, caption_size_max,
            )
            # Fallback: if no whole-block caption sat below the image, scan
            # individual lines — wrap-around layouts park the caption as a
            # single line inside a much bigger body block.
            if not caption_text:
                line_caption, line_keys = _find_caption_in_lines(
                    bbox, page_lines, consumed_line_keys,
                )
                if line_caption:
                    caption_text = line_caption
                    consumed_line_keys.update(line_keys)
            if h in images_by_hash:
                ref = images_by_hash[h]
                # Only attach a caption if the first occurrence didn't get one.
                if caption_text and ref.order not in detected_captions:
                    detected_captions[ref.order] = caption_text
            else:
                file_path = session_media_dir / f"page{page_idx + 1}-{xref}.{ext}"
                file_path.write_bytes(data)
                w, hh = _image_size(file_path)
                ref = ImageRef(
                    src_path=str(file_path.resolve()),
                    sha256=h,
                    order=order,
                    width=w,
                    height=hh,
                    nearby_caption=(caption_text or last_para_text)[:200],
                    mime=f"image/{ext if ext != 'jpg' else 'jpeg'}",
                )
                images_by_hash[h] = ref
                if caption_text:
                    detected_captions[order] = caption_text
                order += 1
            consumed_text_ids.update(used_ids)
            page_items.append((bbox[1], {"image_ref": ref.order}))

        # 4) Emit remaining text blocks as paragraphs / headings, removing
        #    any line-level captions claimed above.
        for idx, tb in enumerate(raw_text_blocks):
            if idx in consumed_text_ids:
                continue
            block_idx = tb.get("block_idx", -1)
            line_records = tb.get("line_records", [])
            if line_records and block_idx >= 0:
                kept = [
                    rec["text"]
                    for li, rec in enumerate(line_records)
                    if rec["text"] and (block_idx, li) not in consumed_line_keys
                ]
                text = " ".join(kept).strip()
            else:
                text = tb["text"]
            if not text:
                continue
            x0, y0, x1, y1 = tb["bbox"]
            sz = tb["size"]
            # Bold-line splitter set kind_hint when it lifted a heading out
            # of a body block; respect it. Otherwise fall back to the font-
            # size thresholds to catch giant title text on cover pages.
            kind_hint = tb.get("kind_hint")
            if kind_hint:
                kind = kind_hint
            elif h1_size > 0 and sz >= h1_size:
                kind = "h1"
            elif h2_size > 0 and sz >= h2_size:
                kind = "h2"
            else:
                kind = "p"
            page_items.append((y0, {"kind": kind, "text": text}))
            if kind == "h1" and sz > detected_title_size:
                detected_title = text.splitlines()[0][:200]
                detected_title_size = sz
            last_para_text = text

        page_items.sort(key=lambda t: t[0])
        for _, item in page_items:
            body.append(item)

    _lift_h3_when_no_h2(body)

    blocks = [TextBlock(kind=b["kind"], text=b["text"]) for b in body if "kind" in b]

    if not detected_title and blocks:
        for b in blocks:
            if b.kind in ("h1", "h2", "p"):
                detected_title = b.text.splitlines()[0][:200]
                break

    # Standfirst: PDF metadata 'subject' field, if present.
    detected_standfirst = (metadata.get("subject") or "").strip()

    # Final pass: catch footnotes the geometry-based detector missed
    # (mid-page footnotes, body-size font, etc.) that got merged into
    # the tail of a paragraph. See _split_orphan_footnotes for details.
    _split_orphan_footnotes(body, footnotes_all)

    # Bind in-body references to the canonical `[^N]` marker. PyMuPDF
    # flattens a superscript footnote digit against its word (`Vietnam1`);
    # convert those to `[^N]` for every number that actually has a
    # footnote, so the body carries the same position markers as the docx
    # path. Numbers without a footnote (years, counts) are left untouched.
    from .footnotes import bind_legacy_digit_refs
    known_ns = {int(fn["n"]) for fn in footnotes_all if "n" in fn}
    for entry in body:
        if "kind" in entry and entry.get("text"):
            entry["text"] = bind_legacy_digit_refs(entry["text"], known_ns)

    # Rebuild the text-only blocks view after the body mutation above.
    blocks = [TextBlock(kind=b["kind"], text=b["text"])
              for b in body if "kind" in b]

    return DocumentDraft(
        source_file=path.name,
        source_sha256=source_sha256,
        detected_title=detected_title,
        detected_author=detected_author,
        detected_standfirst=detected_standfirst,
        blocks=blocks,
        images=sorted(images_by_hash.values(), key=lambda r: r.order),
        body=body,
        detected_captions=detected_captions,
        footnotes=footnotes_all,
    )


# ---------- line-level footnote splitter ----------


def _split_footnote_lines(
    raw_text_blocks: list[dict],
    page_height: float,
    footnote_size_max: float,
    footnotes_all: list[dict],
    page_idx: int,
) -> list[dict]:
    """Lift footnotes off the bottom of each block at the LINE level.

    A footnote zone is the trailing run of lines in a block that are (a) in
    the page's bottom band and (b) set in a font materially smaller than the
    body, where the run BEGINS with a line that reads as a numbered footnote
    (`<n> body…`). Everything from that line to the end of the block is
    footnote content; the body lines above it stay.

    For each footnote lifted, a canonical `[^n]` marker is appended to the
    body paragraph it sat beneath (stripping the flattened superscript digit
    PyMuPDF glued onto the prose, e.g. "…as well.1"), so the note co-locates
    after the right passage. Mutates `footnotes_all`; returns the rebuilt
    block list (footnote-only blocks are dropped).
    """
    if footnote_size_max <= 0:
        return raw_text_blocks
    band_y = page_height * _FOOTNOTE_BAND_FRAC
    out: list[dict] = []

    for tb in raw_text_blocks:
        recs = tb.get("line_records") or []
        # Find where the footnote zone starts: first non-empty line that is
        # in the bottom band, small-font, and reads like a numbered footnote.
        split_at: int | None = None
        for i, rec in enumerate(recs):
            text = (rec.get("text") or "").strip()
            if not text:
                continue
            bbox = rec.get("bbox") or (0, 0, 0, 0)
            y_top = bbox[1] if len(bbox) > 1 else 0
            size = rec.get("size", 0) or 0
            if (
                y_top > band_y
                and 0 < size <= footnote_size_max
                and _FOOTNOTE_LEAD_RE.match(text)
            ):
                split_at = i
                break
        if split_at is None:
            out.append(tb)
            continue

        body_recs = recs[:split_at]
        zone_recs = recs[split_at:]

        # Parse the zone into one or more footnotes. A new footnote starts at
        # a lead-matching line whose number is the next in sequence; every
        # other line is continuation of the current one.
        lifted_nums: list[int] = []
        cur_num: int | None = None
        cur_lines: list[str] = []

        def _flush() -> None:
            nonlocal cur_num, cur_lines
            if cur_num is not None:
                body = " ".join(cur_lines).strip()
                if len(body) >= 6:
                    footnotes_all.append({
                        "n": len(footnotes_all) + 1,
                        "page": page_idx + 1,
                        "local_num": cur_num,
                        "text": body,
                        # Geometry/font heuristic — flag for operator review.
                        "confidence": "low",
                        "source": "pdf_geometry",
                    })
                    lifted_nums.append(len(footnotes_all))  # global n just assigned
            cur_num, cur_lines = None, []

        for rec in zone_recs:
            text = (rec.get("text") or "").strip()
            if not text:
                continue
            m = _FOOTNOTE_LEAD_RE.match(text)
            starts_new = (
                m is not None
                and (cur_num is None or int(m.group(1)) == cur_num + 1)
            )
            if starts_new:
                _flush()
                cur_num = int(m.group(1))
                cur_lines = [m.group(2).strip()]
            elif cur_num is not None:
                cur_lines.append(text)
        _flush()

        body_text = " ".join(r["text"] for r in body_recs if r.get("text")).strip()
        if not body_text:
            # Block was footnote-only — drop it, but the [^n] marker has
            # nowhere to attach. Leave the note as-is; the global validate/
            # renumber pass will surface it if it ends up unreferenced.
            continue

        # Append the canonical marker(s) so the note co-locates here. Strip a
        # trailing flattened superscript digit (the reference glued onto the
        # prose) before appending the first marker.
        if lifted_nums:
            first_local = footnotes_all[lifted_nums[0] - 1].get("local_num")
            if first_local is not None:
                body_text = re.sub(
                    rf"(?<=\D){first_local}\s*$", "", body_text
                ).rstrip()
            body_text = body_text + "".join(f"[^{n}]" for n in lifted_nums)

        nb = dict(tb)
        # Clear line_records so the downstream paragraph rebuild uses this
        # marker-carrying text, not a re-join of the (marker-less) body
        # lines. (Footnote lines have already been removed either way.)
        nb["line_records"] = []
        nb["text"] = body_text
        out.append(nb)

    return out


# ---------- orphan-footnote splitter ----------


# Match a paragraph that ends with a sentence terminator, then a stray
# 1-2 digit number, then a capitalised word, then enough trailing
# content (≥ 25 chars) to suggest a merged-in footnote body.
#
# Guards against false positives:
# - The leading prose must end in [.!?] (a real sentence boundary)
# - The digit must be 1-2 chars (footnote numbers are rarely larger;
#   excludes years like 1966)
# - The capitalised word after the digit signals attribution-style
#   footnote text ("Ex naval rating Jim Cullen advises…"); a lowercase
#   word ("2 weeks later") suggests genuine prose.
_ORPHAN_FOOTNOTE_TAIL_RE = re.compile(
    r"""
    ^(?P<prose>.+?[.!?])               # prose ending in sentence terminator
    \s+(?P<digit>\d{1,2})\s+            # stray 1-2 digit footnote number
    (?P<rest>[A-Z][a-z]+\b.{25,})       # capitalised word + ≥25 chars of body
    $
    """,
    re.VERBOSE | re.DOTALL,
)


def _split_orphan_footnotes(
    body: list[dict], footnotes_all: list[dict],
) -> None:
    """Detect paragraph tails that look like a merged-in footnote and
    split them out into a new footnote entry.

    The geometry-based footnote detector (bottom-band, smaller font)
    misses footnotes that appear mid-page or at body font size. When
    that happens, the footnote body ends up concatenated onto the
    preceding paragraph. The LLM polish later "helpfully" deletes it
    as extraction noise — wrong but understandable.

    Pattern (conservative, false-positive-resistant):

        ...<prose ending in . ! ?> <SPACE> <1-2 digits> <SPACE> <Cap>...

    Splits to:
      - Body: prose with digit attached to the last letter (so the
        inline-footnote rewriter in assemble.py picks it up)
      - Footnote: a new entry in footnotes_all with the trailing text

    Mutates `body` and `footnotes_all` in place. Idempotent: after one
    pass, the body marker is letter+digit so won't match again."""
    known_ns = {int(fn["n"]) for fn in footnotes_all if "n" in fn}

    for entry in body:
        if "kind" not in entry or entry.get("kind") != "p":
            continue
        text = entry.get("text") or ""
        match = _ORPHAN_FOOTNOTE_TAIL_RE.match(text)
        if not match:
            continue

        digit = int(match.group("digit"))
        rest = (match.group("rest") or "").strip()
        if len(rest) < 25:
            continue
        # Already have a footnote at this number — don't overwrite. The
        # operator may have intentionally placed the digit there.
        if digit in known_ns:
            continue

        prose = match.group("prose")
        # Insert a canonical `[^N]` marker immediately after the last
        # alphabetic char in prose so co-located rendering ties the note
        # to this passage. (`[^N]` won't re-match the orphan tail regex,
        # which requires a bare `\s+\d+\s+`, so the split stays idempotent.)
        i = len(prose) - 1
        while i >= 0 and not prose[i].isalpha():
            i -= 1
        if i < 0:
            continue  # no letter to attach to (very unusual)
        new_text = prose[:i + 1] + f"[^{digit}]" + prose[i + 1:]
        entry["text"] = new_text

        # Use the digit as the n if free; otherwise fall back to a fresh
        # sequential id. The marker number must equal n for the ref to
        # resolve to its note at assembly.
        new_n = digit
        known_ns.add(new_n)
        footnotes_all.append({
            "n": new_n,
            "page": 0,            # unknown — we don't track page in the body view
            "local_num": digit,
            "text": rest,
            # Orphan-split is the most heuristic path — always low.
            "confidence": "low",
            "source": "orphan_split",   # debug tag so manifests can be audited
        })


# ---------- bold-line heading splitter ----------


def _split_blocks_at_bold_headings(
    raw_text_blocks: list[dict],
    body_size: float,
    page_width: float = 0.0,
) -> list[dict]:
    """Walk each block's lines. Bold-and-short lines (typical of inline
    section headings the source PDF set at body size) become their own
    blocks with a kind_hint of "h2" (centred, all-caps or year — top-level)
    or "h3" (left-aligned — sub-heading); the lines around them stay as
    ordinary paragraphs. See `_bold_heading_level` for the geometry rule.
    Splitting at the *line* level keeps a heading in document order — its
    block's original y_top is replaced with the line's y_top so reading
    order survives the page-level y-sort.
    """
    out: list[dict] = []
    # The body's left text margin on this page = the leftmost x of any line.
    # A centred heading is indented well right of it; a sub-heading starts at
    # it. Computed once per page from every line bbox.
    xs = [
        r["bbox"][0]
        for tb in raw_text_blocks
        for r in tb.get("line_records", [])
        if r.get("text") and r.get("bbox")
    ]
    page_left = min(xs) if xs else 0.0

    for tb in raw_text_blocks:
        line_records = [r for r in tb.get("line_records", []) if r.get("text")]
        if not line_records:
            out.append(tb)
            continue

        chunks: list[tuple[str, list[dict]]] = []  # (kind, records)
        body_run: list[dict] = []
        for rec in line_records:
            text = rec.get("text", "").strip()
            if not text:
                continue
            is_bold = bool(rec.get("bold"))
            is_short = len(text) <= _HEADING_LINE_MAX_CHARS
            # Promote ONLY when the line is meaningfully wider than the body
            # font *or* clearly an inline header (bold + short). At body
            # size we still need the bold flag to differentiate it.
            if is_bold and is_short:
                if body_run:
                    chunks.append(("p", body_run))
                    body_run = []
                level = _bold_heading_level(
                    text, rec.get("bbox"), page_width, page_left,
                )
                chunks.append((level, [rec]))
            else:
                body_run.append(rec)
        if body_run:
            chunks.append(("p", body_run))

        if len(chunks) == 1 and chunks[0][0] == "p":
            # No headings found; pass the original block through.
            out.append(tb)
            continue

        # Emit one synthetic block per chunk, preserving bbox + size from
        # its lines so caption detection + reading-order sort still work.
        for kind, records in chunks:
            text = " ".join(r["text"] for r in records).strip()
            if not text:
                continue
            sizes = [r.get("size", 0) for r in records if r.get("size", 0) > 0]
            bx0 = min((r["bbox"][0] for r in records if r.get("bbox")), default=tb["bbox"][0])
            by0 = min((r["bbox"][1] for r in records if r.get("bbox")), default=tb["bbox"][1])
            bx1 = max((r["bbox"][2] for r in records if r.get("bbox")), default=tb["bbox"][2])
            by1 = max((r["bbox"][3] for r in records if r.get("bbox")), default=tb["bbox"][3])
            out.append({
                "bbox": (bx0, by0, bx1, by1),
                "text": text,
                "size": max(sizes) if sizes else tb.get("size", body_size),
                "block_idx": tb.get("block_idx", -1),
                "line_records": records,
                "kind_hint": kind if kind != "p" else None,
            })
    return out


# ---------- image tile grouping ----------


def _group_image_tiles(
    raw_images: list[tuple[tuple[float, float, float, float], int, dict]],
) -> list[tuple[tuple[float, float, float, float], list[int]]]:
    """Group image XObjects that share an edge into single 'photos'.

    Word frequently slices a tall or wide photo into multiple PDF image
    XObjects placed edge-to-edge. PyMuPDF reads each as a separate xref,
    so the gallery ends up with disjointed halves. Union-find groups any
    two images whose touching edges are within _TILE_EDGE_GAP and whose
    perpendicular overlap covers ≥ _TILE_OVERLAP_MIN of the shorter side.

    Returns a list of (union_bbox, [xrefs_in_doc_order]).
    """
    n = len(raw_images)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        ax0, ay0, ax1, ay1 = raw_images[i][0]
        a_w = ax1 - ax0
        a_h = ay1 - ay0
        for j in range(i + 1, n):
            bx0, by0, bx1, by1 = raw_images[j][0]
            b_w = bx1 - bx0
            b_h = by1 - by0
            h_overlap = max(0.0, min(ax1, bx1) - max(ax0, bx0))
            v_overlap = max(0.0, min(ay1, by1) - max(ay0, by0))
            # Vertical neighbour: x-bands must overlap by ≥ threshold of
            # BOTH sides — guarantees the two tiles have similar widths.
            if (h_overlap / max(1e-6, max(a_w, b_w)) >= _TILE_OVERLAP_MIN
                and h_overlap / max(1e-6, min(a_w, b_w)) >= _TILE_OVERLAP_MIN):
                v_gap = max(ay0, by0) - min(ay1, by1)
                if abs(v_gap) <= _TILE_EDGE_GAP:
                    union(i, j)
                    continue
            # Horizontal neighbour: same logic on y-bands.
            if (v_overlap / max(1e-6, max(a_h, b_h)) >= _TILE_OVERLAP_MIN
                and v_overlap / max(1e-6, min(a_h, b_h)) >= _TILE_OVERLAP_MIN):
                h_gap = max(ax0, bx0) - min(ax1, bx1)
                if abs(h_gap) <= _TILE_EDGE_GAP:
                    union(i, j)

    groups: dict[int, list[int]] = {}
    for idx in range(n):
        groups.setdefault(find(idx), []).append(idx)

    result: list[tuple[tuple[float, float, float, float], list[int]]] = []
    for member_indices in groups.values():
        # Sort tiles in doc order so the first xref drives stable behaviour.
        member_indices.sort()
        x0 = min(raw_images[i][0][0] for i in member_indices)
        y0 = min(raw_images[i][0][1] for i in member_indices)
        x1 = max(raw_images[i][0][2] for i in member_indices)
        y1 = max(raw_images[i][0][3] for i in member_indices)
        xrefs = [raw_images[i][1] for i in member_indices]
        result.append(((x0, y0, x1, y1), xrefs))
    # Preserve approximate reading order — sort groups by y-top then x-left.
    result.sort(key=lambda g: (round(g[0][1], 1), g[0][0]))
    return result


def _render_tile_group(
    page: fitz.Page,
    bbox: tuple[float, float, float, float],
) -> tuple[str, bytes, str]:
    """Render the visible region covered by a tile group to a JPEG."""
    pix = page.get_pixmap(clip=fitz.Rect(*bbox), dpi=_CROP_RENDER_DPI)
    img_bytes = pix.tobytes("jpeg", jpg_quality=88)
    h = hashlib.sha256(img_bytes).hexdigest()
    return "jpg", img_bytes, h


# ---------- image extraction (crop-aware) ----------


def _extract_image_respecting_crop(
    doc: fitz.Document,
    page: fitz.Page,
    xref: int,
    bbox: tuple[float, float, float, float],
) -> tuple[str, bytes, str]:
    """Return (ext, bytes, sha256) for the image, respecting Word's crops.

    Most photos exit Word intact: the raw XObject bytes match what the reader
    sees. Use those — full resolution, small JPEG/PNG files.

    But when an author cropped a photo in Word, the XObject is the original
    (uncropped) image and only a sub-region is rendered on the page. The raw
    bytes would surface content the author hid. In that case render the
    visible bbox region from the page to a JPEG so the figure matches what
    appears in the PDF.
    """
    raw = doc.extract_image(xref)
    raw_bytes = raw["image"]
    raw_ext = (raw.get("ext", "png") or "png").lower()
    try:
        with Image.open(io.BytesIO(raw_bytes)) as im:
            raw_w, raw_h = im.size
    except Exception:
        raw_w = raw_h = 0
    if raw_h > 0 and raw_w > 0:
        raw_aspect = raw_w / raw_h
        bbox_w = max(1e-6, bbox[2] - bbox[0])
        bbox_h = max(1e-6, bbox[3] - bbox[1])
        bbox_aspect = bbox_w / bbox_h
        relative_diff = abs(raw_aspect - bbox_aspect) / raw_aspect
        if relative_diff <= _CROP_ASPECT_TOLERANCE:
            h = hashlib.sha256(raw_bytes).hexdigest()
            return raw_ext, raw_bytes, h

    # Crop applied — render the visible region from the page itself.
    pix = page.get_pixmap(clip=fitz.Rect(*bbox), dpi=_CROP_RENDER_DPI)
    img_bytes = pix.tobytes("jpeg", jpg_quality=88)
    h = hashlib.sha256(img_bytes).hexdigest()
    return "jpg", img_bytes, h


# ---------- caption detection helpers (line-level) ----------


# Caption-line spatial tolerances mirror the block-level ones.
_LINE_CAPTION_Y_OVERLAP = 35.0
_LINE_CAPTION_Y_BELOW = 40.0
_LINE_CAPTION_X_INSIDE_MIN = 0.7   # fraction of line's x-range inside image
_LINE_CAPTION_MAX_CHARS = 180
_LINE_CAPTION_GAP = 10.0
_LINE_CAPTION_MAX_LINES = 3


def _find_caption_in_lines(
    img_bbox: tuple[float, float, float, float],
    lines: list[dict],
    consumed: set[tuple[int, int]],
) -> tuple[str, list[tuple[int, int]]]:
    """Caption detection scanning the page's *lines*.

    Catches captions that share a block with the body's column-wrap text:
    PyMuPDF emits them as a single block because the lines align by y, but
    the caption itself sits inside the image's x-column while the body
    wraps to the right.
    """
    ix0, iy0, ix1, iy1 = img_bbox
    img_w = max(1.0, ix1 - ix0)
    candidates: list[tuple[float, dict]] = []
    for ln in lines:
        key = (ln["block_idx"], ln["line_idx"])
        if key in consumed:
            continue
        lx0, ly0, lx1, ly1 = ln["bbox"]
        if ly0 < iy1 - _LINE_CAPTION_Y_OVERLAP:
            continue
        if ly0 > iy1 + _LINE_CAPTION_Y_BELOW:
            continue
        # Line must sit predominantly inside the image's x column.
        line_w = max(1e-6, lx1 - lx0)
        overlap = max(0.0, min(lx1, ix1) - max(lx0, ix0))
        if overlap / line_w < _LINE_CAPTION_X_INSIDE_MIN:
            continue
        text = ln["text"]
        if len(text) > _LINE_CAPTION_MAX_CHARS:
            continue
        candidates.append((ly0, ln))
    if not candidates:
        return "", []
    candidates.sort(key=lambda t: t[0])

    selected_keys: list[tuple[int, int]] = []
    selected_text: list[str] = []
    last_y_bottom = -1e9
    for _, ln in candidates:
        if len(selected_text) >= _LINE_CAPTION_MAX_LINES:
            break
        ly0 = ln["bbox"][1]
        ly1 = ln["bbox"][3]
        if selected_text and ly0 - last_y_bottom > _LINE_CAPTION_GAP:
            break
        selected_keys.append((ln["block_idx"], ln["line_idx"]))
        selected_text.append(ln["text"])
        last_y_bottom = ly1

    text = " ".join(t for t in selected_text if t).strip()
    if len(text) > 240:
        text = text[:240].rstrip() + "…"
    return text, selected_keys


# ---------- caption detection helpers (block-level) ----------


# How far below the image bottom a caption may start (points).
_CAPTION_Y_BELOW_TOLERANCE = 40.0
# How far above the image bottom we still accept (caption overlapping bottom edge).
_CAPTION_Y_OVERLAP_TOLERANCE = 35.0
# Vertical gap between consecutive caption lines (continuation).
_CAPTION_LINE_GAP = 10.0
# Minimum horizontal overlap with the image (fraction of image width).
_CAPTION_HORIZONTAL_OVERLAP_MIN = 0.25
# Hard caps on caption length / line count.
_CAPTION_MAX_LINES = 4
_CAPTION_MAX_CHARS = 240


def _find_caption(
    img_bbox: tuple[float, float, float, float],
    text_blocks: list[dict],
    already_consumed: set[int],
    caption_size_max: float,
) -> tuple[str, list[int]]:
    """Find the caption sitting under an image. Returns (text, consumed-idx)."""
    ix0, iy0, ix1, iy1 = img_bbox
    img_w = max(1.0, ix1 - ix0)
    candidates: list[tuple[float, int, dict]] = []
    for idx, tb in enumerate(text_blocks):
        if idx in already_consumed:
            continue
        tx0, ty0, tx1, ty1 = tb["bbox"]
        if ty0 < iy1 - _CAPTION_Y_OVERLAP_TOLERANCE:
            continue
        if ty0 > iy1 + _CAPTION_Y_BELOW_TOLERANCE:
            continue
        # Horizontal overlap fraction relative to the image.
        overlap = max(0.0, min(tx1, ix1) - max(tx0, ix0))
        if overlap / img_w < _CAPTION_HORIZONTAL_OVERLAP_MIN:
            continue
        # Caption text is materially smaller than body text.
        if caption_size_max > 0 and tb["size"] > caption_size_max:
            continue
        # Skip blocks that read like full paragraphs (long, multi-sentence).
        if len(tb["text"]) > _CAPTION_MAX_CHARS:
            continue
        candidates.append((ty0, idx, tb))
    if not candidates:
        return "", []
    candidates.sort(key=lambda t: t[0])

    selected_ids: list[int] = [candidates[0][1]]
    selected_text: list[str] = [_clean_caption_line(candidates[0][2]["text"])]
    last_y_bottom = candidates[0][2]["bbox"][3]
    for ty0, idx, tb in candidates[1:]:
        if len(selected_ids) >= _CAPTION_MAX_LINES:
            break
        if ty0 - last_y_bottom > _CAPTION_LINE_GAP:
            break
        selected_ids.append(idx)
        selected_text.append(_clean_caption_line(tb["text"]))
        last_y_bottom = tb["bbox"][3]

    text = " ".join(t for t in selected_text if t).strip()
    if len(text) > _CAPTION_MAX_CHARS:
        text = text[:_CAPTION_MAX_CHARS].rstrip() + "…"
    return text, selected_ids


def _clean_caption_line(text: str) -> str:
    # Multi-block PDF text often has internal newlines; flatten to a single line.
    return " ".join(text.split()).strip()


# ---------- helpers ----------


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _image_size(p: Path) -> tuple[int, int]:
    try:
        with Image.open(p) as im:
            return im.size
    except Exception:
        return 0, 0


def _collect_font_sizes(doc: fitz.Document) -> list[float]:
    sizes: list[float] = []
    for page in doc:
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    sz = float(span.get("size", 0))
                    if sz > 0:
                        sizes.append(sz)
    return sizes


def _heading_thresholds(sizes: list[float]) -> tuple[float, float]:
    """Return (h1_min, h2_min) by relative size, or (-1, -1) if no signal."""
    if not sizes:
        return -1.0, -1.0
    body_size = _mode_size(sizes)
    if body_size <= 0:
        return -1.0, -1.0
    # H2 at >= 1.2× body; H1 at >= 1.6×. These are coarse but workable for M1.
    return body_size * 1.6, body_size * 1.2


def _mode_size(sizes: list[float]) -> float:
    """Rounded-mode of sizes (most common rounded-to-half-pt)."""
    bins: dict[float, int] = {}
    for s in sizes:
        key = round(s * 2) / 2
        bins[key] = bins.get(key, 0) + 1
    if not bins:
        return 0.0
    return max(bins.items(), key=lambda kv: kv[1])[0]


def _block_dominant_size(page: fitz.Page, bbox: tuple[float, float, float, float]) -> float:
    """Pick the dominant font size within a text block's bbox."""
    sizes: list[float] = []
    for blk in page.get_text("dict", clip=fitz.Rect(*bbox)).get("blocks", []):
        if blk.get("type") != 0:
            continue
        for line in blk.get("lines", []):
            for span in line.get("spans", []):
                sz = float(span.get("size", 0))
                if sz > 0:
                    sizes.append(sz)
    if not sizes:
        return 0.0
    return max(sizes)
