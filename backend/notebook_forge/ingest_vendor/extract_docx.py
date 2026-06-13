"""DOCX extraction — unpack media + pandoc → GFM, dedupe identical bytes.

Per spec §6 S2: "unpack (docx skill's `unpack.py`) to get word/media/*;
pandoc … -t gfm --wrap=none for body; reconcile each <img> reference to
its media file in document order. (Dedup identical media by hash …)"

Pandoc is the source of truth for body text; it writes only the image
references actually used (so byte-identical duplicates inside word/media
that pandoc never referenced are dropped automatically). We still hash
every file pandoc emitted to fold duplicates that *both* got referenced.
"""

from __future__ import annotations

import hashlib
import html as _html
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image

from .model import DocumentDraft, ImageRef, TextBlock

PANDOC_REQUIRED = "pandoc (install with `brew install pandoc`)"

# Pandoc emits images in TWO forms, and a real-world memoir hits both:
#   1. GFM markdown:  ![alt](src)
#   2. Raw HTML:      <img src="…" style="width:3.79in;height:2.87in" …/>
# Form 2 is pandoc's fallback whenever a docx image carries attributes it
# can't express in pure GFM — explicit width/height being the usual
# culprit, and almost every Word document sizes its images. If we only
# match form 1 (as the original regex did), a richly-formatted memoir
# extracts ZERO figures even though every image is present on disk.
#
# `_IMG_RE` matches either form. Group 1 = markdown src, group 2 = HTML
# src; exactly one is non-None per match. The HTML branch is tolerant of
# attribute order (src need not come first) and of single or double
# quotes. Pandoc's `alt` on the HTML form is the original filesystem path
# (e.g. C:\Users\Bob\Pictures\…) — junk we deliberately ignore.
_IMG_RE = re.compile(
    r"!\[[^\]]*\]\(([^)]+)\)"                                  # 1: GFM  ![](src)
    r"|<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"'][^>]*?>",    # 2: HTML <img src="">
    re.IGNORECASE,
)


# Pandoc emits an image's caption as a <figcaption> inside the <figure>, e.g.
#   <figcaption><p><strong>Observing Sigma Octantis…</strong></p></figcaption>
# This is the author's EXPLICIT figure caption (pandoc lifts it from the docx
# Caption-styled paragraph or the image's title) — the most reliable caption
# signal we have, and one the XML next-paragraph heuristic can miss.
_FIGCAPTION_RE = re.compile(
    r"<figcaption\b[^>]*>(.*?)</figcaption>", re.IGNORECASE | re.DOTALL
)


def _figcaption_text(segment: str) -> str | None:
    """If a text segment is a pandoc ``<figcaption>`` block, return its
    plain-text caption (inner p/strong/em stripped, entities unescaped);
    otherwise None. An empty figcaption returns ``""`` so the caller still
    knows to drop the segment without recording a blank caption."""
    m = _FIGCAPTION_RE.search(segment)
    if not m:
        return None
    inner = re.sub(r"<[^>]+>", "", m.group(1))
    return _html.unescape(inner).strip()


def _normalise_pandoc_images(md: str) -> str:
    """Collapse pandoc's multi-line ``<figure><img …></figure>`` blocks.

    A SIZED image becomes raw HTML pandoc can't express in GFM, and newer
    pandoc pretty-prints that ``<img …>`` across several lines inside a
    ``<figure>`` wrapper. The body parser works line by line, so a split
    ``<img>`` never matches ``_IMG_RE`` and the figure is lost (the bare
    ``<figure>`` even leaks in as a paragraph). Join each ``<img …>`` onto a
    single line and drop the ``<figure>`` wrappers so single-line matching
    works for both Word- and python-docx-authored documents."""
    md = re.sub(r"<img\b[^>]*?>", lambda m: " ".join(m.group(0).split()), md, flags=re.S)
    md = re.sub(r"[ \t]*</?figure>[ \t]*", "", md)
    return md


def extract_docx(path: Path, session_media_dir: Path) -> DocumentDraft:
    """Extract a DOCX into a DocumentDraft. Media land in session_media_dir."""
    path = path.resolve()
    if not _pandoc_available():
        raise RuntimeError(f"DOCX extraction needs {PANDOC_REQUIRED}.")

    session_media_dir.mkdir(parents=True, exist_ok=True)
    source_sha256 = _sha256_file(path)

    # Pandoc extracts media as a sibling of the output. Use a clean dir.
    if session_media_dir.exists():
        for child in session_media_dir.iterdir():
            if child.is_file():
                child.unlink()

    md_path = session_media_dir.parent / "_pandoc_body.md"
    # `--extract-media` puts files under <dir>/media/. Point pandoc at our session dir.
    cmd = [
        "pandoc",
        "-f", "docx",
        "-t", "gfm",
        "--wrap=none",
        "--extract-media", str(session_media_dir.parent),
        "-o", str(md_path),
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)

    # Pandoc writes media to <session>/media/media/<file>. Flatten one level.
    nested = session_media_dir / "media"
    if nested.exists():
        for f in nested.iterdir():
            target = session_media_dir / f.name
            if target.exists():
                target.unlink()
            shutil.move(str(f), str(target))
        nested.rmdir()

    body_md = _normalise_pandoc_images(md_path.read_text(encoding="utf-8"))

    # docProps/core.xml: title, author, subject (→ standfirst default).
    title, author, subject = _read_core_props(path)

    # Walk body, collect ordered text + image refs. Dedupe images by hash.
    images, body, figcaptions = _parse_pandoc_body(body_md, session_media_dir)

    # Capture the doc's 'image then bold caption' convention BEFORE heading
    # promotion can mistake those caption lines for section heads.
    body, bold_captions = _harvest_adjacent_bold_captions(body)

    # Lift pandoc's footnote definitions (`[^N]: text`) out of the body
    # into the canonical footnote model. The `[^N]` references stay in
    # their paragraphs as the position markers. Pandoc reads
    # word/footnotes.xml internally and emits these GFM footnotes with
    # exact in-body positions, so this is the reliable docx mapping.
    footnotes, body = _extract_pandoc_footnotes(body)

    # Promote hand-styled bold section heads to real headings. Pandoc only
    # maps Word *Heading* styles to `#`; authors who bold-and-centre their
    # section heads instead produce **…** paragraphs that would otherwise
    # render as a flat wall of bold prose. The PDF path already does this
    # (bold-short lines → h2); this keeps Word imports at parity.
    body = _promote_bold_paragraph_headings(body)

    # First non-empty paragraph guess for title fallback (heading-less docs).
    # Strip any wholly-wrapping bold/italic markers so the masthead never
    # shows literal ** / * (the title line is often a hand-bolded paragraph).
    if not title:
        for b in body:
            if b.get("kind") in ("h1", "h2", "p"):
                title = _strip_emphasis(b["text"])
                break

    blocks = [TextBlock(kind=b["kind"], text=b["text"]) for b in body if "kind" in b]

    # Captions: walk the raw docx XML for Caption-styled paragraphs that
    # follow images. This is the high-confidence signal (caption_source =
    # "original"). The pandoc-driven body[] doesn't carry style info, so we
    # rely on the underlying XML and align by image order.
    detected_captions = _extract_caption_map(path)
    # Pandoc <figcaption> blocks are the author's explicit figure captions —
    # the strongest signal. Fill in any image the XML next-paragraph heuristic
    # missed (it doesn't override a caption the XML pass already found).
    for order, cap in figcaptions.items():
        detected_captions.setdefault(order, cap)
    for order, cap in bold_captions.items():
        detected_captions.setdefault(order, cap)

    draft = DocumentDraft(
        source_file=str(path.name),
        source_sha256=source_sha256,
        detected_title=title,
        detected_author=author,
        detected_standfirst=subject,
        blocks=blocks,
        images=images,
        body=body,
        detected_captions=detected_captions,
        footnotes=footnotes,
    )
    return draft


# ---------------------------------------------------------------- helpers


def _pandoc_available() -> bool:
    return shutil.which("pandoc") is not None


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_core_props(docx: Path) -> tuple[str, str, str]:
    """Return (title, author, subject) from docProps/core.xml; '' if missing."""
    try:
        with zipfile.ZipFile(docx) as z:
            raw = z.read("docProps/core.xml")
    except (KeyError, zipfile.BadZipFile):
        return "", "", ""
    ns = {
        "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
        "dc": "http://purl.org/dc/elements/1.1/",
    }
    try:
        tree = ET.fromstring(raw)
    except ET.ParseError:
        return "", "", ""
    title = (tree.findtext("dc:title", default="", namespaces=ns) or "").strip()
    author = (tree.findtext("dc:creator", default="", namespaces=ns) or "").strip()
    subject = (tree.findtext("dc:subject", default="", namespaces=ns) or "").strip()
    return title, author, subject


_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = {"w": _W_NS}
_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_WPS_NS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"


def _extract_caption_map(docx: Path) -> dict[int, str]:
    """Return {image_order: caption_text} for images whose next paragraph is
    a Word Caption-styled paragraph. Image order matches the order pandoc
    walks the body (top-to-bottom in document.xml)."""
    try:
        with zipfile.ZipFile(docx) as z:
            doc_xml = z.read("word/document.xml")
            try:
                styles_xml = z.read("word/styles.xml")
            except KeyError:
                styles_xml = b""
    except (KeyError, zipfile.BadZipFile):
        return {}

    caption_style_ids = _caption_style_ids(styles_xml)

    try:
        root = ET.fromstring(doc_xml)
    except ET.ParseError:
        return {}
    body = root.find(f"{{{_W_NS}}}body")
    if body is None:
        return {}

    # Pre-pass: dedupe by image hash, the same way the main extractor does.
    # We track image_order via *unique* hashes since pandoc emits one
    # reference per unique image. Without media bytes here we approximate by
    # the embed ID — same embed → same image.
    paragraphs = list(body.findall(f"{{{_W_NS}}}p"))
    seen_embed_ids: list[str] = []  # embed id in order of first appearance
    embed_index_by_paragraph: list[list[int]] = []  # per-paragraph embed indexes
    for p in paragraphs:
        embeds = _paragraph_embed_ids(p)
        idx_list: list[int] = []
        for e in embeds:
            if e in seen_embed_ids:
                idx_list.append(seen_embed_ids.index(e))
            else:
                seen_embed_ids.append(e)
                idx_list.append(len(seen_embed_ids) - 1)
        embed_index_by_paragraph.append(idx_list)

    captions: dict[int, str] = {}
    for i, p in enumerate(paragraphs):
        if not embed_index_by_paragraph[i]:
            continue

        # Priority 1: text inside the image's grouped drawing (text boxes
        # nested in <wps:txbx>). The user's sample doc keeps captions like
        # "Baby Junior" here rather than in a separate styled paragraph.
        txbox = _paragraph_drawing_textbox_text(p)
        if txbox:
            for img_idx in embed_index_by_paragraph[i]:
                captions.setdefault(img_idx, txbox)
            continue

        # Priority 2: the next paragraph if it carries a Caption style
        # or is short + centered (Word's manual-caption convention).
        if i + 1 >= len(paragraphs):
            continue
        next_p = paragraphs[i + 1]
        if embed_index_by_paragraph[i + 1]:
            continue
        style = _paragraph_style(next_p)
        text = _paragraph_text(next_p)
        if not text:
            continue
        looks_like_caption = (
            style.lower() in caption_style_ids
            or (len(text) <= 140 and _paragraph_centered(next_p))
        )
        if not looks_like_caption:
            continue
        for img_idx in embed_index_by_paragraph[i]:
            captions.setdefault(img_idx, text)
    return captions


def _caption_style_ids(styles_xml: bytes) -> set[str]:
    """Return lowercase style IDs whose w:name is 'caption'."""
    if not styles_xml:
        return {"caption"}    # safe default
    try:
        root = ET.fromstring(styles_xml)
    except ET.ParseError:
        return {"caption"}
    ids: set[str] = set()
    for style in root.findall(f"{{{_W_NS}}}style"):
        name_el = style.find(f"{{{_W_NS}}}name")
        if name_el is None:
            continue
        name = (name_el.get(f"{{{_W_NS}}}val") or "").strip().lower()
        if name == "caption":
            sid = (style.get(f"{{{_W_NS}}}styleId") or "").strip().lower()
            if sid:
                ids.add(sid)
    ids.add("caption")        # Word's default style ID is literally "Caption"
    return ids


def _paragraph_embed_ids(p: ET.Element) -> list[str]:
    """Return embed (relationship) IDs of inline/anchored images in p, in order."""
    ids: list[str] = []
    for blip in p.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip"):
        rid = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
        if rid:
            ids.append(rid)
    return ids


def _paragraph_style(p: ET.Element) -> str:
    pPr = p.find(f"{{{_W_NS}}}pPr")
    if pPr is None:
        return ""
    pStyle = pPr.find(f"{{{_W_NS}}}pStyle")
    if pStyle is None:
        return ""
    return (pStyle.get(f"{{{_W_NS}}}val") or "").strip()


def _paragraph_centered(p: ET.Element) -> bool:
    pPr = p.find(f"{{{_W_NS}}}pPr")
    if pPr is None:
        return False
    jc = pPr.find(f"{{{_W_NS}}}jc")
    if jc is None:
        return False
    return (jc.get(f"{{{_W_NS}}}val") or "").strip().lower() == "center"


def _paragraph_text(p: ET.Element) -> str:
    parts: list[str] = []
    for t in p.iter(f"{{{_W_NS}}}t"):
        if t.text:
            parts.append(t.text)
    return "".join(parts).strip()


def _paragraph_drawing_textbox_text(p: ET.Element) -> str:
    """Return the text inside grouped-drawing text boxes (<wps:txbx>) for the
    paragraph, deduplicated and cleaned. This is where the test memoir keeps
    its captions (the floating "Baby Junior" frame above the image)."""
    parts: list[str] = []
    for txbx in p.iter(f"{{{_WPS_NS}}}txbx"):
        # txbx contains a w:txbxContent → w:p chain. Pull all w:t leaves.
        chunk = " ".join(
            (t.text or "").strip()
            for t in txbx.iter(f"{{{_W_NS}}}t")
            if t.text and t.text.strip()
        ).strip()
        if chunk:
            parts.append(chunk)
    if not parts:
        return ""
    raw = " ".join(parts)
    return _collapse_repeats(raw)


def _collapse_repeats(text: str) -> str:
    """Word sometimes echoes text-box content twice in the XML (once for the
    visible frame, once for accessibility). Collapse exact "X X" duplicates."""
    s = " ".join(text.split())   # normalise whitespace
    if not s:
        return ""
    # Try exact-half split: "Baby Junior Baby Junior" → "Baby Junior"
    half = len(s) // 2
    for cut in range(max(1, half - 4), half + 5):
        if cut <= 0 or cut >= len(s):
            continue
        if s[cut] != " ":
            continue
        left, right = s[:cut].strip(), s[cut + 1:].strip()
        if left and left == right:
            return left
    return s


def _extract_pandoc_footnotes(
    body: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Split pandoc's GFM footnote definitions out of the body.

    Returns (footnotes, new_body). A definition is a paragraph whose text
    is `[^N]: note text` (pandoc emits these, one per footnote, at the end
    of the document with --wrap=none). They become canonical footnote
    entries `{"n", "text", "confidence": "high", "source": "docx"}`; the
    `[^N]` *references* inside other paragraphs are left in place as the
    position markers.

    confidence is "high" because pandoc read the structured
    word/footnotes.xml — the number↔text↔position mapping is exact, not
    heuristic (unlike the PDF path)."""
    from .footnotes import DEFINITION_RE

    footnotes: list[dict] = []
    new_body: list[dict] = []
    for e in body:
        if e.get("kind") == "p":
            m = DEFINITION_RE.match((e.get("text") or "").strip())
            if m:
                text = m.group(2).strip()
                if text:
                    footnotes.append({
                        "n": int(m.group(1)),
                        "text": text,
                        "confidence": "high",
                        "source": "docx",
                    })
                continue  # drop the definition paragraph from the body
        new_body.append(e)
    footnotes.sort(key=lambda fn: fn["n"])
    return footnotes, new_body


def _heading_kind(line: str) -> tuple[str, str] | None:
    m = re.match(r"^(#{1,3})\s+(.*?)\s*#*\s*$", line)
    if not m:
        return None
    level = len(m.group(1))
    kind = f"h{level}"
    return kind, m.group(2).strip()


# ---------- bold-paragraph heading promotion (docx ↔ PDF parity) ----------
#
# Pandoc maps only real Word *Heading* styles to Markdown `#`. Authors who
# style their section heads by hand — bold, often centred — instead produce
# a wholly-bold paragraph **Heading**, which pandoc renders as `**…**` and
# our body parser keeps as an ordinary <p>. The PDF path already promotes
# bold-short lines to h2 (extract_pdf._split_blocks_at_bold_headings); this
# is the docx mirror so a Word import gets the same section structure rather
# than a flat wall of bold paragraphs.
#
# Char ceiling matches the PDF splitter's _HEADING_LINE_MAX_CHARS so both
# formats draw the heading/prose line at the same place.
_HEADING_MAX_CHARS = 100
_BOLD_ONLY_RE = re.compile(r"^\*\*(.+?)\*\*$", re.DOTALL)
_ITALIC_ONLY_RE = re.compile(r"^\*(?!\*)(.+?)\*$", re.DOTALL)
# Pandoc emits raw HTML for inline styles GFM can't express natively.
# Strip the tags, keeping their text content (e.g. 1<sup>st</sup> → 1st).
_RAW_SUP_SUB_RE = re.compile(r"</?su[pb][^>]*>", re.IGNORECASE)


def _strip_emphasis(text: str) -> str:
    """Strip a single wholly-wrapping bold/italic span plus pandoc's stray
    backslash escapes. Used to clean the title fallback so the masthead
    never shows literal ** / * markers."""
    t = (text or "").strip()
    m = _BOLD_ONLY_RE.match(t) or _ITALIC_ONLY_RE.match(t)
    if m:
        t = m.group(1).strip()
    return t.replace("\\", "").strip()


def _as_bold_heading(entry: dict) -> dict | None:
    """If `entry` is a paragraph whose ENTIRE text is a single bold span and
    short enough to read as a heading, return an {kind, text} dict with the
    ** markers stripped. Otherwise None.

    Heading level is inferred from capitalisation — a convention common in
    memoir-style Word documents where authors style section heads by hand:
      - All alphabetic characters UPPERCASE → h2 (major section, e.g. "KAPOOKA")
      - Mixed case → h3 (subsection, e.g. "Off to Kapooka")

    Rejects:
      - paragraphs with bold only on part of the text (prose with an
        emphasised phrase — the inner text would still contain `**`),
      - anything longer than a heading would plausibly be,
      - bold sentences ending in sentence-final punctuation (.!?), which are
        emphasised prose, not section heads.
    """
    if entry.get("kind") != "p":
        return None
    text = (entry.get("text") or "").strip()
    m = _BOLD_ONLY_RE.match(text)
    if not m:
        return None
    inner = m.group(1).strip()
    if not inner or "**" in inner:
        return None
    if len(inner) > _HEADING_MAX_CHARS:
        return None
    if inner[-1] in ".!?":
        return None
    # Pandoc escapes stray characters with backslashes (e.g. a trailing "\").
    inner = inner.replace("\\", "").strip()
    if not inner:
        return None
    alpha = [c for c in inner if c.isalpha()]
    kind = "h2" if alpha and all(c.isupper() for c in alpha) else "h3"
    return {"kind": kind, "text": inner}


def _is_prose_block(entry: dict) -> bool:
    """An ordinary body paragraph — NOT an image, NOT a wholly bold/italic
    caption-or-heading line. The presence of prose next to a bold line is
    what distinguishes a section heading (introduces prose) from a gallery
    caption (embedded in a run of images with no prose between)."""
    if "image_ref" in entry:
        return False
    text = (entry.get("text") or "").strip()
    if not text:
        return False
    if _BOLD_ONLY_RE.match(text) or _ITALIC_ONLY_RE.match(text):
        return False
    return True


def _is_gallery_caption(body: list[dict], i: int, window: int = 1) -> bool:
    """True when the bold paragraph at i reads as a photo-gallery caption,
    not a section heading.

    Adjacency to an image alone is too crude — a real section head can sit
    right after a figure. The reliable signal is the *immediate
    neighbourhood*: a gallery caption sits in a run of image / caption /
    image with an image hard against it and no ordinary prose touching it,
    whereas a section head always has the prose it introduces (or the prior
    section's prose) immediately beside it. So: adjacent to an image AND no
    prose paragraph within ±window → caption.

    window=1 (immediate neighbours only) is deliberately tight: it keeps the
    first caption in a gallery from being mis-promoted just because the last
    body paragraph happens to sit a couple of blocks above it, while still
    catching every section head (which always abuts prose)."""
    prev_img = i > 0 and "image_ref" in body[i - 1]
    next_img = i + 1 < len(body) and "image_ref" in body[i + 1]
    if not (prev_img or next_img):
        return False
    lo, hi = max(0, i - window), min(len(body), i + window + 1)
    for j in range(lo, hi):
        if j != i and _is_prose_block(body[j]):
            return False
    return True


def _promote_bold_paragraph_headings(body: list[dict]) -> list[dict]:
    """Promote wholly-bold short paragraphs to h2 — except gallery captions.

    Then, if the document ended up with no h1 at all (common for memoirs
    whose title is itself a hand-styled bold line rather than a Word Heading
    style), lift the first heading to h1 so the title anchors the document
    and clean._strip_front_matter can drop the duplicated preamble — exactly
    as it does for the PDF path, whose font-size pass yields an h1 title."""
    out: list[dict] = []
    for i, e in enumerate(body):
        promoted = _as_bold_heading(e)
        if promoted is not None and not _is_gallery_caption(body, i):
            out.append(promoted)
        else:
            out.append(e)

    if not any(e.get("kind") == "h1" for e in out):
        for e in out:
            if e.get("kind") in ("h2", "h3"):
                e["kind"] = "h1"
                break
    return out


def _strip_inline_emph(text: str) -> str:
    """Strip raw HTML tags pandoc emits for inline styles GFM can't express
    (e.g. <sup>st</sup> for Word ordinal superscripts). Keep inner text."""
    text = _RAW_SUP_SUB_RE.sub("", text)
    return text.strip()


def _harvest_adjacent_bold_captions(
    body: list[dict],
) -> tuple[list[dict], dict[int, str]]:
    """Capture the common 'image(s) then a bold caption line' convention.

    Many memoirs caption a figure with a wholly-bold paragraph placed right
    after the image — and after a *run* of images for a side-by-side pair —
    instead of using Word's Caption style. The XML caption pass only sees
    Caption-styled/centred paragraphs, so these are missed; the bold-heading
    promoter can even mistake them for section heads.

    For each wholly-bold paragraph sitting immediately after one or more
    consecutive image refs (no text between), record it as the caption for
    every image in that run and drop the paragraph from the body. Runs BEFORE
    heading promotion so these caption lines never reach it. Returns the pruned
    body and {image_order: caption}.

    A bold line NOT adjacent to an image is left alone — that's a real section
    head (e.g. a bold-styled chapter title in a run of prose)."""
    caps: dict[int, str] = {}
    drop: set[int] = set()
    for i, e in enumerate(body):
        if e.get("kind") != "p":
            continue
        m = _BOLD_ONLY_RE.match((e.get("text") or "").strip())
        if not m:
            continue
        inner = m.group(1)
        if "**" in inner:          # malformed / nested bold — skip
            continue
        inner = inner.replace("\\", "").strip()
        if not inner:
            continue
        # Walk back over the run of image refs immediately before this line.
        run: list[int] = []
        j = i - 1
        while j >= 0 and "image_ref" in body[j]:
            run.append(body[j]["image_ref"])
            j -= 1
        if not run:
            continue
        for order in run:
            caps.setdefault(order, inner)
        drop.add(i)
    if not drop:
        return body, caps
    return [e for k, e in enumerate(body) if k not in drop], caps


def _parse_pandoc_body(
    md: str, media_dir: Path,
) -> tuple[list[ImageRef], list[dict], dict[int, str]]:
    """Walk pandoc's GFM output line by line. Splits image refs out of paragraphs.

    Returns (deduped ImageRef list in first-appearance order, body[],
    figcaptions). body[] is an ordered mix of text-block dicts {"kind","text"}
    and image refs {"image_ref": <order>}. figcaptions maps image order →
    caption text harvested from pandoc <figcaption> blocks (and those blocks
    are dropped from body[] rather than leaking in as junk paragraphs).
    """
    body: list[dict] = []
    by_hash: dict[str, ImageRef] = {}  # hash → canonical ImageRef
    order_counter = 0
    last_para_text: str | None = None  # for nearby_caption back-fill
    figcaptions: dict[int, str] = {}
    last_image_order: int | None = None

    paragraphs = _paragraphs(md)

    for para in paragraphs:
        # A paragraph may interleave image refs with text. Split.
        segments = _split_image_segments(para)
        had_image_in_para = False
        for kind, payload in segments:
            if kind == "image":
                src = payload
                local_path = _resolve_local_image(src, media_dir)
                if not local_path or not local_path.exists():
                    continue
                data = local_path.read_bytes()
                h = _sha256_bytes(data)
                if h in by_hash:
                    # Duplicate of an earlier image; we still want to record the
                    # *position* (so the body interleaving is faithful), but
                    # reference the same canonical ImageRef.
                    ref = by_hash[h]
                else:
                    width, height = _image_size(local_path)
                    ref = ImageRef(
                        src_path=str(local_path.relative_to(media_dir.parent.parent)) if media_dir.is_relative_to(media_dir.parent.parent) else str(local_path),
                        sha256=h,
                        order=order_counter,
                        width=width,
                        height=height,
                        nearby_caption=(last_para_text or "")[:200],
                        mime=_guess_mime(local_path.name),
                    )
                    by_hash[h] = ref
                    order_counter += 1
                body.append({"image_ref": ref.order})
                last_image_order = ref.order
                had_image_in_para = True
            elif kind == "text":
                # A pandoc <figcaption> is the image's explicit caption — record
                # it against the preceding image and drop the block (it must not
                # become a body paragraph).
                cap = _figcaption_text(payload)
                if cap is not None:
                    if cap and last_image_order is not None:
                        figcaptions.setdefault(last_image_order, cap)
                    continue
                # Pull heading out if the segment is heading-shaped.
                h_kind = _heading_kind(payload.strip())
                if h_kind:
                    kind_name, text = h_kind
                    body.append({"kind": kind_name, "text": text})
                    last_para_text = text
                else:
                    txt = _strip_inline_emph(payload)
                    if txt:
                        body.append({"kind": "p", "text": txt})
                        last_para_text = txt
        # If the paragraph contained both an image and following text, the text
        # block is already in `body`; nothing more to do.
        _ = had_image_in_para  # noqa: F841

    images = sorted(by_hash.values(), key=lambda r: r.order)
    return images, body, figcaptions


def _paragraphs(md: str) -> list[str]:
    """Split GFM into paragraphs (blank-line separated)."""
    parts = re.split(r"\n\s*\n", md.strip())
    return [p.strip() for p in parts if p.strip()]


def _split_image_segments(paragraph: str) -> list[tuple[str, str]]:
    """Yield ('image', src) and ('text', chunk) in order across a paragraph.

    Handles both pandoc image forms — GFM ![](src) and raw <img src="">.
    The whole image token (markdown or the entire <img …> tag) is
    consumed, so no attribute/HTML cruft leaks into the text segments."""
    out: list[tuple[str, str]] = []
    pos = 0
    for m in _IMG_RE.finditer(paragraph):
        if m.start() > pos:
            chunk = paragraph[pos:m.start()].strip()
            if chunk:
                out.append(("text", chunk))
        # Exactly one branch matched — markdown src (g1) or HTML src (g2).
        src = m.group(1) if m.group(1) is not None else m.group(2)
        out.append(("image", src))
        pos = m.end()
    if pos < len(paragraph):
        chunk = paragraph[pos:].strip()
        if chunk:
            out.append(("text", chunk))
    return out


def _resolve_local_image(src: str, media_dir: Path) -> Path | None:
    """Map a pandoc image src to a file under media_dir."""
    # Pandoc may emit absolute paths (when --extract-media is absolute) or
    # relative ones. Strip directory components and look up by basename.
    name = Path(src).name
    candidate = media_dir / name
    if candidate.exists():
        return candidate
    # Fall back to any matching basename in the dir tree.
    for f in media_dir.iterdir():
        if f.name == name:
            return f
    return None


def _image_size(p: Path) -> tuple[int, int]:
    try:
        with Image.open(p) as im:
            return im.size
    except Exception:
        return 0, 0


def _guess_mime(name: str) -> str:
    n = name.lower()
    if n.endswith(".png"):
        return "image/png"
    if n.endswith(".gif"):
        return "image/gif"
    if n.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"
