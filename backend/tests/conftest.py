from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from notebook_forge.db import make_engine, make_session_factory


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    return tmp_path / "ws"


@pytest.fixture()
def session(workspace: Path) -> Iterator[Session]:
    engine = make_engine(workspace)
    factory = make_session_factory(engine)
    with factory() as s:
        yield s
    engine.dispose()
