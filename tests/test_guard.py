import pytest

from src.guard import ContentGuard, ContentRejected, parse_terms

guard = ContentGuard.from_terms(["Empresa X", "GD", "projeto ômega"])


@pytest.mark.parametrize("text", [
    "Authorization: Bearer " + "x" * 32,
    "-----BEGIN " + "RSA PRIVATE KEY-----",
    "AKIA" + "Z" * 16,
    "AIza" + "B" * 35,
    "ghp_" + "a" * 36,
    "sk-" + "ant-" + "x" * 24,
    "eyJ" + "a" * 12 + ".eyJ" + "b" * 12 + "." + "c" * 12,
    "token: " + "0123abcd" * 8,
    'password = "' + "q" * 12 + '"',
])
def test_detects_credentials(text):
    with pytest.raises(ContentRejected, match="credencial"):
        guard.check(conteudo=text)


@pytest.mark.parametrize("text", [
    "Commit 3f786850e387550fdab836ed7e6dc881de23001b corrigiu o bug",
    "token = os.environ['AUTH_TOKEN']",
    "Use o header Authorization: Bearer <token>",
    "gcloud secrets versions access latest --secret=second-brain-auth-token",
])
def test_allows_common_technical_text(text):
    guard.check(conteudo=text)


@pytest.mark.parametrize("text", [
    "Deploy na EMPRESA X",
    "Regra do projeto Omega",
    "Planilha de rateio GD",
])
def test_blocks_terms_ignoring_case_and_accents(text):
    with pytest.raises(ContentRejected, match="termo bloqueado"):
        guard.check(titulo=text)


def test_blocked_term_matches_whole_words_only():
    guard.check(conteudo="Configurei o GDAL e o pgdump")


def test_checks_lists_and_skips_none():
    guard.check(conteudo="ok", projeto=None, tags=["django", "fastapi"])
    with pytest.raises(ContentRejected, match="'tags'"):
        guard.check(tags=["django", "gd"])


def test_parse_terms():
    assert parse_terms(" Empresa X, ,GD ,") == ["Empresa X", "GD"]
    assert parse_terms(None) == []


def test_guard_without_terms_only_checks_credentials():
    ContentGuard().check(conteudo="Empresa X e GD")
