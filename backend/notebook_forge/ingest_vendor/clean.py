"""Heading normalisation + doc-preamble stripping.

Spec §6 S3:
  - Single H1 (the title), logical H2/H3
  - Strip junk (page numbers, repeated headers)

In practice memoirs from Word tend to lead with a self-contained title
block — bare-paragraph title, author, subtitle, date — followed by an H1
that introduces the actual content. Once the operator confirms their own
masthead at CP1, those preamble paragraphs duplicate the header and need
to be dropped. We treat "everything up to and including the first H1" as
front matter and strip it.

If the document has no H1 at all (an unusual but possible shape), we
leave the body alone — there's nothing safe to identify as preamble.
"""

from __future__ import annotations

from .model import DocumentDraft, TextBlock
from .polish import polish_body


def normalise(draft: DocumentDraft) -> DocumentDraft:
    """Strip doc-preamble, demote extra H1s, run the deterministic polish
    pass (locale quotes + rejoin page-break splits), then the global
    footnote renumber."""
    _strip_front_matter(draft)
    _demote_extra_h1s(draft)
    # Slide a figure out of the middle of a sentence: PDFs embed images in
    # the text column, so document-order extraction can drop a figure (and
    # its caption) mid-paragraph, splitting the sentence. Runs before polish
    # so the rejoined paragraph is polished as one block.
    draft.body = _relocate_sentence_splitting_figures(draft.body)
    # A figure's caption sometimes lands in the body as a duplicate heading
    # (a short bold caption line gets promoted by the PDF bold-heading
    # splitter even though caption detection already claimed it). Drop the
    # body copy — the caption belongs under the figure, not as a section head.
    _dedupe_caption_headings(draft)
    draft.body = polish_body(draft.body)
    # Global, deterministic footnote pass on the canonical [^N] model:
    # gap-free 1..N by first reference, drop notes never referenced. Runs
    # here — BEFORE assembly, with a whole-document view — and is kept
    # OUT of the chunked LLM polish, which can't see across chunks.
    from .renumber import renumber_footnotes
    renumber_footnotes(draft)
    # Keep blocks[] in sync with body[] after the passes above.
    draft.blocks = [
        TextBlock(kind=e["kind"], text=e["text"])
        for e in draft.body if "kind" in e
    ]
    return draft


def _strip_front_matter(draft: DocumentDraft) -> None:
    """Drop everything up to and including the first H1 in body[].

    This assumes the common Word-memoir shape: a bare-paragraph title block
    (title / author / subtitle / date) followed by the first H1 that opens
    the real content. We only strip when the document actually has that
    shape — i.e. no section heading (H2/H3) appears before the first H1.

    Guard against a destructive misfire: some authors hand-style every
    section head as a bold paragraph (which we promote to H2) and leave a
    single stray Word *Heading 1* deep in the document. Treating that lone
    late H1 as the front-matter boundary would delete the entire body before
    it (observed: ~38 pages lost). When an H2/H3 precedes the first H1, the
    leading content isn't a title block, so we leave the body untouched."""
    cut = _first_h1_index(draft.body)
    if cut is None:
        return
    if any(e.get("kind") in ("h2", "h3") for e in draft.body[:cut]):
        # Real sections precede the first H1 — not a title-block boundary.
        return
    # Preserve image refs that appear in the front matter — they're real
    # content and we don't want to silently lose figures whose ordering
    # placed them before the main heading. (Rare but worth being safe.)
    preamble = draft.body[: cut + 1]
    salvaged_images = [e for e in preamble if "image_ref" in e]
    draft.body = salvaged_images + draft.body[cut + 1:]
    # blocks[] is the heading/paragraph-only view; rebuild from the new body.
    draft.blocks = [
        TextBlock(kind=e["kind"], text=e["text"])
        for e in draft.body if "kind" in e
    ]


def _first_h1_index(body: list[dict]) -> int | None:
    for i, e in enumerate(body):
        if e.get("kind") == "h1":
            return i
    return None


def _demote_extra_h1s(draft: DocumentDraft) -> None:
    """Keep the first H1 (if any survived front-matter stripping), demote rest."""
    seen_h1 = False
    new_blocks: list[TextBlock] = []
    new_body: list[dict] = []
    for b in draft.blocks:
        if b.kind == "h1":
            if seen_h1:
                new_blocks.append(TextBlock(kind="h2", text=b.text))
                continue
            seen_h1 = True
        new_blocks.append(b)
    draft.blocks = new_blocks

    seen_h1 = False
    for entry in draft.body:
        if entry.get("kind") == "h1":
            if seen_h1:
                new_body.append({"kind": "h2", "text": entry["text"]})
                continue
            seen_h1 = True
        new_body.append(entry)
    draft.body = new_body


# ---------------------------------------------------------------- caption dedupe


def _dedupe_caption_headings(draft: DocumentDraft) -> None:
    """Drop a body heading/paragraph that duplicates a figure's caption.

    The PDF caption detector records `{image_order: caption}` in
    draft.detected_captions, and that caption renders under the figure. But
    a short bold caption line (e.g. "Baby Junior") also gets promoted to an
    h2 by the bold-heading splitter, so the same text appears twice — once
    as the figure caption, once as a stray section heading. This removes the
    body copy: for each image_ref, if a nearby block's text exactly equals
    that figure's detected caption, drop it. Adjacency + exact match keep a
    genuine heading that happens to share words from being removed."""
    caps = {
        int(k): (v or "").strip()
        for k, v in (draft.detected_captions or {}).items()
        if (v or "").strip()
    }
    if not caps:
        return
    body = draft.body
    remove: set[int] = set()
    for i, e in enumerate(body):
        if "image_ref" not in e:
            continue
        cap = caps.get(e["image_ref"])
        if not cap:
            continue
        # Captions sit immediately beside their image — check only the two
        # adjacent blocks so a real heading further away can't be removed.
        for j in (i - 1, i + 1):
            if j < 0 or j >= len(body) or j in remove:
                continue
            b = body[j]
            if b.get("kind") in ("h2", "h3", "p") and (b.get("text") or "").strip() == cap:
                remove.add(j)
                break
    if remove:
        draft.body = [e for k, e in enumerate(body) if k not in remove]
        draft.blocks = [
            TextBlock(kind=e["kind"], text=e["text"])
            for e in draft.body if "kind" in e
        ]


# ---------------------------------------------------------------- figure relocation


# Sentence-final once trailing closing quotes/brackets are stripped.
_SENTENCE_END = ".!?…"


def _ends_sentence(text: str) -> bool:
    t = (text or "").rstrip().rstrip('"”’\')]')
    return bool(t) and t[-1] in _SENTENCE_END


def _starts_lowercase(text: str) -> bool:
    t = (text or "").lstrip().lstrip('"“‘\'([')
    return bool(t) and t[0].islower()


def _relocate_sentence_splitting_figures(body: list[dict]) -> list[dict]:
    """Move a figure that splits a sentence to just after the sentence.

    Pattern (PDF image embedded mid-column):
        p:    "...the Second World War. Tragic as they were for"   (no terminator)
        image
        h2/h3: "Baby Junior"   (the figure's caption, 0+ of these)
        p:    "many, for a small boy they were great fun..."       (lowercase → continuation)

    becomes:
        p:    "...Tragic as they were for many, for a small boy they were great fun..."
        image
        h2/h3: "Baby Junior"

    Conservative guards keep it from firing on a real paragraph/figure
    boundary: the preceding paragraph must NOT end a sentence, the following
    paragraph MUST start lowercase, and the only blocks between them are the
    image and short caption-style headings. Image order indices are
    untouched, so figure↔caption mapping in assembly is preserved."""
    out = list(body)
    i = 1
    while i < len(out):
        if "image_ref" not in out[i]:
            i += 1
            continue
        prev = out[i - 1]
        if prev.get("kind") != "p" or _ends_sentence(prev.get("text", "")):
            i += 1
            continue
        # Collect the figure run: the image plus any short caption-style
        # headings, up to the next paragraph.
        j = i
        run: list[dict] = []
        while j < len(out) and (
            "image_ref" in out[j]
            or (out[j].get("kind") in ("h2", "h3")
                and len(out[j].get("text") or "") <= 100)
        ):
            run.append(out[j])
            j += 1
        # Need a continuation paragraph that starts lowercase right after.
        if j >= len(out) or out[j].get("kind") != "p":
            i += 1
            continue
        cont = out[j]
        cont_text = (cont.get("text") or "").lstrip()
        if not _starts_lowercase(cont_text):
            i += 1
            continue
        # Rejoin the split sentence onto the preceding paragraph, drop the
        # continuation block, and re-insert the figure run after it.
        prev["text"] = (prev.get("text", "").rstrip() + " " + cont_text).strip()
        del out[i:j + 1]            # remove run + continuation
        out[i:i] = run             # re-insert the figure run after prev
        i += len(run)
    return out
