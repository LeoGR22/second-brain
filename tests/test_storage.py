"""Comportamento do storage, executado nos dois backends (SQLite e Firestore fake)."""

import time


def _save(storage, **kw):
    data = {"titulo": "Título", "conteudo": "Conteúdo", "categoria": "geral"}
    data.update(kw)
    mem = storage.save_memory(**data)
    time.sleep(0.002)  # garante created_at distintos para a ordenação
    return mem


def test_save_normalizes_fields(storage):
    mem = _save(storage, titulo="  Bug no Docker  ", categoria="BugFix",
                tags=[" Docker ", "docker", "GitLab CI"], projeto="  Meu-App ")

    stored = storage.get_memory(mem["id"])
    assert stored["titulo"] == "Bug no Docker"
    assert stored["categoria"] == "bugfix"
    assert stored["tags"] == ["docker", "gitlab ci"]
    assert stored["projeto"] == "Meu-App"
    assert stored["projeto_key"] == "meu-app"


def test_search_by_text_category_tag_and_project(storage):
    a = _save(storage, titulo="Cache no Redis", categoria="arquitetura", tags=["redis"], projeto="API")
    b = _save(storage, titulo="Deploy no Cloud Run", conteudo="usar --set-secrets", tags=["gcp"], projeto="api")
    _save(storage, titulo="Outro", tags=["python"], projeto="site")

    assert [m["id"] for m in storage.search_memories(query="secrets")] == [b["id"]]
    assert [m["id"] for m in storage.search_memories(categoria="Arquitetura")] == [a["id"]]
    assert {m["id"] for m in storage.search_memories(projeto="API")} == {a["id"], b["id"]}
    assert [m["id"] for m in storage.search_memories(tag="Redis")] == [a["id"]]


def test_tag_filter_is_exact_match(storage):
    _save(storage, tags=["python"])
    assert storage.search_memories(tag="py") == []


def test_search_orders_newest_first_and_respects_limit(storage):
    ids = [_save(storage, titulo=f"m{i}", tags=["x"])["id"] for i in range(5)]
    assert [m["id"] for m in storage.search_memories(tag="x", limit=3)] == ids[::-1][:3]
    assert [m["id"] for m in storage.search_memories(limit=2)] == ids[::-1][:2]


def test_text_search_finds_old_memories(storage):
    old = _save(storage, titulo="Solução antiga", conteudo="agulha")
    for i in range(30):
        _save(storage, titulo=f"recente {i}")
    assert [m["id"] for m in storage.search_memories(query="agulha", limit=5)] == [old["id"]]


def test_update_changes_only_given_fields(storage):
    mem = _save(storage, titulo="Antigo", conteudo="v1", tags=["a"], projeto="X")
    updated = storage.update_memory(mem["id"], conteudo="v2", tags=["B"], titulo=None)

    assert updated["titulo"] == "Antigo"
    assert updated["conteudo"] == "v2"
    assert updated["tags"] == ["b"]
    assert updated["updated_at"] >= mem["updated_at"]
    assert storage.get_memory(mem["id"])["conteudo"] == "v2"
    assert storage.update_memory("nao-existe", conteudo="x") is None


def test_delete_moves_to_trash(storage):
    mem = _save(storage, titulo="Remover", tags=["t"])

    assert storage.delete_memory(mem["id"]) is True
    assert storage.get_memory(mem["id"]) is None
    assert storage.search_memories(tag="t") == []
    assert storage.delete_memory(mem["id"]) is False


def test_list_recent(storage):
    mem = _save(storage, titulo="Hoje")
    assert [m["id"] for m in storage.list_recent(days=1)] == [mem["id"]]


def test_portfolio_summary(storage):
    _save(storage, titulo="Entrega A", categoria="portfolio", tags=["python", "gcp"], projeto="P1")
    _save(storage, titulo="Estudo", categoria="estudo", tags=["python"])

    summary = storage.portfolio_summary()
    assert summary["total_analisado"] == 2
    assert summary["principais_skills_e_tags"][0] == ("python", 2)
    assert summary["projetos_envolvidos"] == [("P1", 1)]
    assert [h["titulo"] for h in summary["destaques_para_curriculo"]] == ["Entrega A"]


def test_firestore_uses_emulator_host(monkeypatch):
    import os

    from src.storage import FirestoreStorage

    # setenv registra o valor original, para o monkeypatch restaurar o ambiente no fim do teste
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "")
    storage = FirestoreStorage(project_id="demo-second-brain", emulator_host="localhost:8085")

    assert os.environ["FIRESTORE_EMULATOR_HOST"] == "localhost:8085"
    assert storage.db.project == "demo-second-brain"
