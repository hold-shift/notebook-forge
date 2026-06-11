"""Vendored MemoirForge extraction pipeline (read-only source:
/Users/cs/ClaudeCode/MemoirForge/memoirforge/, copied 11 June 2026).

These modules carry the proven PDF/DOCX extraction logic — caption
geometry, footnote lifting/binding, heading normalisation, date
detection — with imports adjusted and the LLM-polish stage removed.
Behavioural changes are deliberately avoided; fixes belong upstream
first or as adapters in notebook_forge.ingestion.
"""

from .clean import normalise
from .dates import detect_year_range
from .extract_docx import extract_docx
from .extract_pdf import extract_pdf
from .model import DocumentDraft, ImageRef, TextBlock

__all__ = [
    "DocumentDraft", "ImageRef", "TextBlock",
    "detect_year_range", "extract_docx", "extract_pdf", "normalise",
]
