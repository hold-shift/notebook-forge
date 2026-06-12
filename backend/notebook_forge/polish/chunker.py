"""Split a polishable block list into LLM-sized chunks on heading/paragraph boundaries.

Ported from MemoirForge llm_polish/chunker.py.
Key divergence: BlockRef.id is the BlockNote UUID string (not a synthetic
"b0042" index); chunk_blocks takes list[tuple[str, str, str]] (block_id,
kind, text) rather than list[TextBlock].
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BlockRef:
    """A polishable block paired with its position in the polishable list."""
    block_id: str  # BlockNote UUID
    idx: int
    kind: str
    text: str

    @property
    def id(self) -> str:
        return self.block_id

    @property
    def estimated_tokens(self) -> int:
        return max(1, len(self.text) // 4)


@dataclass
class Chunk:
    """A contiguous block range bundled for one LLM call."""
    idx: int
    blocks: list[BlockRef]
    context_block: BlockRef | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def estimated_tokens(self) -> int:
        ctx = self.context_block.estimated_tokens if self.context_block else 0
        return ctx + sum(b.estimated_tokens for b in self.blocks)

    @property
    def block_ids(self) -> list[str]:
        return [b.id for b in self.blocks]


_HEADING_KINDS = {"h1", "h2", "h3"}


def chunk_blocks(
    blocks: list[tuple[str, str, str]],
    *,
    target_tokens: int = 3500,
    max_tokens: int | None = None,
    overlap_blocks: int = 1,
) -> list[Chunk]:
    """Split polishable blocks into LLM-sized chunks.

    Args:
        blocks: list of (block_id, kind, text) from polishable_blocks().
        target_tokens: soft cap per chunk (default 3500).
        max_tokens: hard cap (defaults to target_tokens * 2).
        overlap_blocks: preceding blocks attached as context only (default 1).
    """
    if not blocks:
        return []
    if max_tokens is None:
        max_tokens = target_tokens * 2
    if overlap_blocks < 0:
        overlap_blocks = 0

    refs = [
        BlockRef(block_id=bid, idx=i, kind=kind, text=text)
        for i, (bid, kind, text) in enumerate(blocks)
    ]
    chunks: list[Chunk] = []
    i = 0
    while i < len(refs):
        first = refs[i]
        accum = [first]
        total = first.estimated_tokens
        notes: list[str] = []

        if total > max_tokens:
            notes.append(
                f"block {first.id[:8]}… alone is ~{total} tokens "
                f"(> max {max_tokens}); LLM may truncate"
            )
            j = i + 1
        else:
            chunk_has_paragraph = first.kind not in _HEADING_KINDS
            j = i + 1
            while j < len(refs):
                nxt = refs[j]
                # Start a new chunk at a heading when this one already has body.
                if nxt.kind in _HEADING_KINDS and chunk_has_paragraph:
                    break
                projected = total + nxt.estimated_tokens
                if projected > target_tokens:
                    break
                accum.append(nxt)
                total = projected
                if nxt.kind not in _HEADING_KINDS:
                    chunk_has_paragraph = True
                j += 1

        ctx = refs[i - 1] if i > 0 and overlap_blocks > 0 else None
        chunks.append(Chunk(idx=len(chunks), blocks=accum, context_block=ctx, notes=notes))
        i = j

    return chunks
