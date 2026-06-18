"""Gemini report runner via httpx.

Mirrors polish/runner.py: same generateContent endpoint, `x-goog-api-key`,
keychain key via `sketch.get_gemini_key`, one retry on parse failure, and a
concurrent `run_chunks` with a progress callback. The model id is config-driven
(default `gemini-3.5-flash`) and the runner sits behind a thin interface so a
future Claude runner — the transport the standalone reference actually used —
can drop in unchanged.

Two call shapes:
- digest_chapter(): one chapter → the structured-digest JSON object.
- consolidate(): the whole-document executive summary + selected anchors.
Both send SYSTEM_RULES as the Gemini systemInstruction and the per-call
instruction as the user content.
"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .chunker import ReportChunk
from .serializer import (
    ReportParseError,
    build_chapter_prompt,
    build_consolidate_prompt,
    build_system_rules,
    parse_chapter_json,
    parse_consolidate_json,
)

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
REPORT_MODEL = "gemini-3.5-flash"

_MAX_TOKENS_CHAPTER = 20_000
_MAX_TOKENS_CONSOLIDATE = 4_000


class GeminiReportRunner:
    def __init__(
        self,
        api_key: str,
        model: str = REPORT_MODEL,
        transport=None,  # noqa: ANN001 — httpx transport override for tests
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.transport = transport

    def _call(self, system: str, user: str, max_tokens: int) -> str:
        import httpx

        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens},
        }
        with httpx.Client(transport=self.transport, timeout=180) as client:
            resp = client.post(
                GEMINI_ENDPOINT.format(model=self.model),
                headers={"x-goog-api-key": self.api_key},
                json=body,
            )
        resp.raise_for_status()
        data = resp.json()
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if "text" in part:
                    return part["text"]
        raise RuntimeError("Gemini response contained no text part")

    def digest_chapter(
        self, chunk: ReportChunk, source_name: str, *, extra_rules: str = ""
    ) -> dict[str, Any]:
        """One chapter → structured digest dict, with up to one retry."""
        system = build_system_rules(extra_rules)
        prompt = build_chapter_prompt(source_name, chunk.title, chunk.text)
        last_error = ""
        for attempt in range(2):
            try:
                raw = self._call(system, prompt, _MAX_TOKENS_CHAPTER)
                return parse_chapter_json(raw)
            except ReportParseError as exc:
                last_error = str(exc)
                if attempt == 0:
                    prompt = (
                        prompt
                        + f"\n\n[Your previous reply failed: {last_error}. "
                        "Return ONE valid JSON object exactly as specified.]"
                    )
                    continue
                raise
        raise RuntimeError(f"chapter digest failed after retry: {last_error}")

    def consolidate(
        self,
        source_name: str,
        years: str,
        chapters_data: list[tuple[str, dict[str, Any]]],
        *,
        stated: list[str] | None = None,
        inference: list[str] | None = None,
        inconsistencies: list[str] | None = None,
        extra_rules: str = "",
    ) -> dict[str, Any]:
        """Whole-document executive summary + anchors + curated §3/§4 lists.

        The pooled raw `stated` / `inference` / `inconsistencies` lists (from
        service) are sent for synthesis and serve as the fallbacks if the model
        omits a curated field.
        """
        stated = stated or []
        inference = inference or []
        inconsistencies = inconsistencies or []
        digests = "\n\n".join(
            f"## {title}\n{data.get('digest_md', '')}" for title, data in chapters_data
        )
        candidates = [a for _, data in chapters_data for a in data.get("anchors", [])]
        system = build_system_rules(extra_rules)
        prompt = build_consolidate_prompt(
            source_name, years, digests, candidates, stated, inference, inconsistencies
        )
        try:
            raw = self._call(system, prompt, _MAX_TOKENS_CONSOLIDATE)
            return parse_consolidate_json(raw, candidates, stated, inference, inconsistencies)
        except ReportParseError:
            # Consolidation is non-fatal: fall back to the raw pooled material.
            return {
                "executive_summary": "",
                "anchors": candidates[:8],
                "interpersonal_stated": stated,
                "interpersonal_inference": inference,
                "inconsistencies": inconsistencies,
            }


def make_runner(model: str = REPORT_MODEL, transport=None) -> GeminiReportRunner:  # noqa: ANN001
    """Real runner when a Gemini key is configured; raises RuntimeError otherwise."""
    from ..sketch import get_gemini_key

    api_key = get_gemini_key()
    if not api_key:
        raise RuntimeError(
            "report generation is not configured: no Gemini API key found "
            "(set it with: uv run keyring set notebook-forge gemini-api-key)"
        )
    return GeminiReportRunner(api_key, model=model, transport=transport)


def run_chunks(
    chunks: list[ReportChunk],
    runner: GeminiReportRunner,
    source_name: str,
    *,
    extra_rules: str = "",
    on_chunk_done: Callable[[bool], None] | None = None,
) -> tuple[list[tuple[str, dict[str, Any]]], list[str]]:
    """Run every chapter concurrently (4 workers), preserving chapter order.

    Returns (chapters_data, failed_notes) where chapters_data is the list of
    (title, digest_dict) in chunk order for chapters that succeeded.

    on_chunk_done is called once per completed chunk with failed=True/False;
    callback errors are swallowed so they can never tank the run.
    """
    results: dict[int, tuple[str, dict[str, Any]]] = {}
    failed: list[str] = []

    def run_one(chunk: ReportChunk) -> tuple[int, str, dict[str, Any] | None, str]:
        try:
            data = runner.digest_chapter(chunk, source_name, extra_rules=extra_rules)
            return chunk.idx, chunk.title, data, ""
        except Exception as exc:  # noqa: BLE001 — recorded as a failed chunk
            return chunk.idx, chunk.title, None, f"chapter {chunk.idx} ({chunk.title}): {exc}"

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(run_one, chunk): chunk for chunk in chunks}
        for fut in as_completed(futs):
            idx, title, data, err = fut.result()
            if err:
                failed.append(err)
            elif data is not None:
                results[idx] = (title, data)
            if on_chunk_done is not None:
                try:
                    on_chunk_done(bool(err))
                except Exception:  # noqa: BLE001
                    pass

    ordered = [results[idx] for idx in sorted(results)]
    return ordered, failed
