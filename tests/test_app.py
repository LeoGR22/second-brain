"""Testes de ponta a ponta do servidor HTTP + MCP (backend SQLite)."""

import json

import pytest
from fastapi.testclient import TestClient

from src.main import app

# Host igual ao do Cloud Run, para garantir que o servidor não responde 421
BASE_URL = "https://second-brain-mcp-abc123-uc.a.run.app"
HEADERS = {
    "Authorization": "Bearer test-token",
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


@pytest.fixture(scope="module")
def client():
    with TestClient(app, base_url=BASE_URL) as c:
        yield c


def rpc(client, method, params=None, *, headers=HEADERS, req_id=1):
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
    return client.post("/mcp", json=payload, headers=headers, follow_redirects=False)


def parse(response) -> dict:
    """Extrai o JSON-RPC da resposta (SSE ou JSON puro)."""
    text = response.text
    if text.lstrip().startswith("{"):
        return json.loads(text)
    data = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
    return json.loads(data[-1])


def call_tool(client, name, arguments):
    result = parse(rpc(client, "tools/call", {"name": name, "arguments": arguments}))["result"]
    return result["content"][0]["text"]


def test_health_is_public(client):
    assert client.get("/health").json()["status"] == "healthy"


def test_docs_are_not_exposed(client):
    assert client.get("/openapi.json", headers=HEADERS).status_code == 404


def test_mcp_requires_token(client):
    assert rpc(client, "initialize", headers={**HEADERS, "Authorization": ""}).status_code == 401
    assert rpc(client, "initialize", headers={**HEADERS, "Authorization": "Bearer errado"}).status_code == 403


def test_initialize_on_cloud_run_host(client):
    response = rpc(client, "initialize", {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "1"},
    })
    assert response.status_code == 200
    assert parse(response)["result"]["serverInfo"]["name"] == "SecondBrain"


def test_tools_are_listed(client):
    tools = {t["name"] for t in parse(rpc(client, "tools/list"))["result"]["tools"]}
    assert {"salvar_memoria", "atualizar_memoria", "buscar_memorias", "remover_memoria"} <= tools


def test_save_update_search_and_remove_through_mcp(client):
    saved = call_tool(client, "salvar_memoria", {
        "titulo": "Fix do lifespan do MCP",
        "conteudo": "Montar o app MCP na raiz e rodar session_manager no lifespan.",
        "categoria": "bugfix",
        "tags": ["MCP", "fastapi"],
        "projeto": "second-brain",
    })
    memory_id = saved.split("ID: ")[1].split("\n")[0]

    assert "atualizada" in call_tool(client, "atualizar_memoria", {"memoria_id": memory_id, "tags": ["mcp", "cloud-run"]})
    found = call_tool(client, "buscar_memorias", {"tag": "cloud-run"})
    assert memory_id in found and "Fix do lifespan" in found

    assert "lixeira" in call_tool(client, "remover_memoria", {"memoria_id": memory_id})
    assert "Nenhuma memória" in call_tool(client, "buscar_memorias", {"tag": "cloud-run"})
