"""Gemini-only polish runner via httpx.

Pattern mirrors sketch_gen.GeminiSketchGenerator: same REST endpoint,
same transport= override for tests, same keychain lookup.

Run behaviour:
- ONE retry per chunk on parse failure or coverage < 1.0; a terse
  "your previous reply failed because …" note is appended to the prompt.
- A chunk that fails twice is recorded as failed; its blocks are left
  untouched (the service marks them in failed_chunks).
- All chunks run concurrently with 4 workers (ThreadPoolExecutor).
"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
POLISH_MODEL = "gemini-2.5-flash"


class GeminiPolishRunner:
    def __init__(
        self,
        api_key: str,
        model: str = POLISH_MODEL,
        transport=None,  # noqa: ANN001 — httpx transport override for tests
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.transport = transport

    def _call(self, prompt: str) -> str:
        import httpx

        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0},
        }
        with httpx.Client(transport=self.transport, timeout=120) as client:
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

    def run_chunk(
        self,
        chunk: Any,  # Chunk from chunker.py
        *,
        extra_rules: str = "",
    ) -> dict[str, str]:
        """Run one chunk with up to one retry.  Returns {block_id: polished_text}."""
        from .serializer import (
            SerializationError,
            coverage_ratio,
            parse_polished_jsonl,
            serialize_chunk_for_prompt,
        )

        prompt = serialize_chunk_for_prompt(chunk, extra_rules=extra_rules)
        last_error: str = ""

        for attempt in range(2):
            try:
                raw = self._call(prompt)
                result = parse_polished_jsonl(raw, chunk)
                ratio = coverage_ratio(result, chunk)
                if ratio < 1.0:
                    reason = f"only {ratio:.0%} of blocks returned"
                    if attempt == 0:
                        prompt = (
                            prompt
                            + f"\n\n[Previous reply was incomplete — {reason}."
                            f" Return ALL {len(chunk.blocks)} POLISH lines.]"
                        )
                        last_error = reason
                        continue
                    raise SerializationError(f"coverage {ratio:.0%} after retry")
                return result
            except SerializationError as exc:
                if attempt == 0:
                    last_error = str(exc)
                    prompt = (
                        prompt
                        + f"\n\n[Previous reply failed: {last_error}. Try again.]"
                    )
                    continue
                raise

        raise RuntimeError(f"chunk failed after retry: {last_error}")


def make_runner(model: str = POLISH_MODEL, transport=None) -> GeminiPolishRunner:  # noqa: ANN001
    """Real runner when a Gemini key is configured; raises RuntimeError otherwise."""
    from ..sketch import get_gemini_key

    api_key = get_gemini_key()
    if not api_key:
        raise RuntimeError(
            "polish is not configured: no Gemini API key found "
            "(set it with: uv run keyring set notebook-forge gemini-api-key)"
        )
    return GeminiPolishRunner(api_key, model=model, transport=transport)


def run_chunks(
    chunks: list[Any],
    runner: GeminiPolishRunner,
    *,
    extra_rules: str = "",
    on_chunk_done: Callable[[bool], None] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Run all chunks concurrently (4 workers).

    Returns (results, failed_notes) where results is {block_id: polished_text}
    and failed_notes is a list of human-readable error strings.

    on_chunk_done is called once per completed chunk with failed=True/False.
    Callback errors are swallowed — they must never tank the run.
    """
    combined: dict[str, str] = {}
    failed: list[str] = []

    def run_one(chunk: Any) -> tuple[int, dict[str, str] | None, str]:
        try:
            return chunk.idx, runner.run_chunk(chunk, extra_rules=extra_rules), ""
        except Exception as exc:
            return chunk.idx, None, f"chunk {chunk.idx}: {exc}"

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(run_one, chunk): chunk for chunk in chunks}
        for fut in as_completed(futs):
            idx, result, err = fut.result()
            if err:
                failed.append(err)
            elif result:
                combined.update(result)
            if on_chunk_done is not None:
                try:
                    on_chunk_done(bool(err))
                except Exception:
                    pass

    return combined, failed
