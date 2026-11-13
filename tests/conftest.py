import os
import sys
import tempfile
from pathlib import Path

import pytest

# Configuração antes de importar o app (src.server instancia o storage no import)
_TMP = tempfile.mkdtemp(prefix="second-brain-tests-")
os.environ.update(
    AUTH_TOKEN="test-token",
    STORAGE_BACKEND="sqlite",
    SQLITE_DB_PATH=str(Path(_TMP) / "app.db"),
    BLOCKED_TERMS="Empresa X, projeto ômega",
)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage import FirestoreStorage, SQLiteStorage  # noqa: E402
from tests.fake_firestore import FakeFirestoreClient  # noqa: E402


@pytest.fixture(params=["sqlite", "firestore"])
def storage(request, tmp_path):
    """Roda cada teste de storage nos dois backends, garantindo o mesmo comportamento."""
    if request.param == "sqlite":
        return SQLiteStorage(db_path=str(tmp_path / "memories.db"))
    return FirestoreStorage(collection_name="mem", client=FakeFirestoreClient())
