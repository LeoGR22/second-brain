import pytest
from pydantic import ValidationError

from src.config import Settings


def test_sqlite_accepts_dev_token():
    assert Settings(_env_file=None, storage_backend="sqlite", auth_token="dev-secret-token").auth_token


@pytest.mark.parametrize("token", ["dev-secret-token", "curto"])
def test_firestore_rejects_weak_token(token):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, storage_backend="firestore", auth_token=token)


def test_firestore_accepts_strong_token():
    Settings(_env_file=None, storage_backend="firestore", auth_token="a" * 64)


def test_invalid_backend_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, storage_backend="postgres")
