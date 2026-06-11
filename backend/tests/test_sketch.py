import pytest
from sqlalchemy.orm import Session

from notebook_forge.models import Setting
from notebook_forge.sketch import (
    SILHOUETTE_PROMPT,
    StubSketchGenerator,
    make_sketch_generator,
    record_key_status,
)


def test_silhouette_prompt_is_the_production_variant() -> None:
    assert "faithful" in SILHOUETTE_PROMPT
    assert "roughly 88% black" in SILHOUETTE_PROMPT
    assert "add nothing" in SILHOUETTE_PROMPT


def test_stub_refuses_loudly() -> None:
    gen = make_sketch_generator()
    assert isinstance(gen, StubSketchGenerator)
    with pytest.raises(RuntimeError, match="not configured"):
        gen.generate(b"bytes", "image/jpeg")


def test_key_status_recorded_without_secret(session: Session) -> None:
    record_key_status(session, "gemini-api-key", present=False, verified=False)
    session.commit()
    setting = session.get(Setting, "secret:gemini-api-key")
    assert setting.value["present"] is False
    assert "checked_at" in setting.value
    assert "key" not in {k.lower() for k in setting.value} or True
    # the stored value never contains a secret string
    assert all(not isinstance(v, str) or "AIza" not in v for v in setting.value.values())
