"""Whitespace- and attribute-order-insensitive DOM comparison.

Used by the M3 idempotency gate and the M4 round-trip report. Documents are
flattened to token streams (open-tag + normalised attrs, collapsed text,
close-tag); similarity is the SequenceMatcher ratio over the two streams and
a diff is the list of non-equal opcodes with surrounding context.

JSON-LD scripts are compared as parsed JSON (canonical dump) so key order
and spacing never count as differences.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

_WS = re.compile(r"\s+")

Token = tuple[str, str]


def _collapse(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _attrs_signature(tag: Tag) -> str:
    parts = []
    for key in sorted(tag.attrs):
        value = tag.attrs[key]
        if isinstance(value, list):
            value = " ".join(value)
        parts.append(f'{key}="{_collapse(str(value))}"')
    return " ".join(parts)


def tokenize(html: str) -> list[Token]:
    soup = BeautifulSoup(html, "lxml")
    tokens: list[Token] = []

    def walk(node: Tag) -> None:
        for child in node.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                text = _collapse(str(child))
                if text:
                    tokens.append(("text", text))
                continue
            if not isinstance(child, Tag):
                continue
            if child.name == "script":
                sig = _attrs_signature(child)
                content = child.string or ""
                if child.get("type") == "application/ld+json":
                    try:
                        content = json.dumps(json.loads(content), sort_keys=True)
                    except ValueError:
                        content = _collapse(content)
                else:
                    content = _collapse(content)
                tokens.append(("script", f"<script {sig}>{content}"))
                continue
            if child.name == "style":
                tokens.append(("style", _collapse(child.get_text())))
                continue
            tokens.append(("open", f"<{child.name} {_attrs_signature(child)}".rstrip()))
            walk(child)
            tokens.append(("close", f"</{child.name}>"))

    walk(soup)
    return tokens


@dataclass
class DiffEntry:
    op: str
    context_before: list[str]
    expected: list[str]
    actual: list[str]
    context_after: list[str]


@dataclass
class CompareResult:
    similarity: float
    total_nodes: int
    diffs: list[DiffEntry]

    @property
    def equal(self) -> bool:
        return not self.diffs


def compare(expected_html: str, actual_html: str, context: int = 2) -> CompareResult:
    a = tokenize(expected_html)
    b = tokenize(actual_html)
    matcher = SequenceMatcher(a=a, b=b, autojunk=False)
    diffs: list[DiffEntry] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        diffs.append(
            DiffEntry(
                op=op,
                context_before=[t[1] for t in a[max(0, i1 - context) : i1]],
                expected=[t[1] for t in a[i1:i2]],
                actual=[t[1] for t in b[j1:j2]],
                context_after=[t[1] for t in a[i2 : i2 + context]],
            )
        )
    return CompareResult(
        similarity=matcher.ratio(),
        total_nodes=max(len(a), len(b)),
        diffs=diffs,
    )
