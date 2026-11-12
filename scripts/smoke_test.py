"""Teste de fumaça do servidor MCP usando o cliente oficial do protocolo.

Faz o mesmo caminho que o Antigravity: conecta, lista as ferramentas e executa
salvar -> buscar -> atualizar -> remover com uma memória de teste (que vai para a lixeira no final).

Uso:
    # local (servidor rodando com `python -m src.main`)
    python scripts/smoke_test.py --url http://localhost:8080/mcp --token dev-secret-token

    # Cloud Run
    python scripts/smoke_test.py --url https://<seu-servico>.run.app/mcp --token <token>

O token também pode vir da variável de ambiente AUTH_TOKEN.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

EXPECTED_TOOLS = {
    "salvar_memoria", "atualizar_memoria", "buscar_memorias", "listar_atividades_recentes",
    "obter_memoria_por_id", "remover_memoria", "gerar_resumo_portfolio",
}


def ok(msg: str) -> None:
    print(f"  [ok] {msg}")


async def call(session: ClientSession, tool: str, args: dict) -> str:
    result = await session.call_tool(tool, args)
    text = result.content[0].text if result.content else ""
    if result.isError:
        raise RuntimeError(f"{tool} retornou erro: {text}")
    return text


async def run(url: str, token: str) -> None:
    tag = f"smoke-{uuid.uuid4().hex[:8]}"
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(headers=headers, timeout=60) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                info = await session.initialize()
                ok(f"conectado ao servidor '{info.serverInfo.name}'")

                tools = {t.name for t in (await session.list_tools()).tools}
                missing = EXPECTED_TOOLS - tools
                if missing:
                    raise RuntimeError(f"ferramentas ausentes: {sorted(missing)}")
                ok(f"{len(tools)} ferramentas disponíveis")

                saved = await call(session, "salvar_memoria", {
                    "titulo": "Memória de teste (smoke test)",
                    "conteudo": "Criada pelo scripts/smoke_test.py. Pode ser ignorada.",
                    "categoria": "geral",
                    "tags": [tag],
                })
                memory_id = saved.split("ID: ")[1].split("\n")[0].strip()
                ok(f"salvar_memoria -> {memory_id}")

                found = await call(session, "buscar_memorias", {"tag": tag})
                assert memory_id in found, "a memória salva não apareceu na busca"
                ok("buscar_memorias encontrou a memória")

                await call(session, "atualizar_memoria", {"memoria_id": memory_id, "conteudo": "Conteúdo atualizado."})
                detail = await call(session, "obter_memoria_por_id", {"memoria_id": memory_id})
                assert "Conteúdo atualizado." in detail, "a atualização não foi aplicada"
                ok("atualizar_memoria aplicou a mudança")

                await call(session, "remover_memoria", {"memoria_id": memory_id})
                after = await call(session, "buscar_memorias", {"tag": tag})
                assert memory_id not in after, "a memória continuou aparecendo depois de removida"
                ok("remover_memoria moveu para a lixeira")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8080/mcp")
    parser.add_argument("--token", default=os.getenv("AUTH_TOKEN"))
    args = parser.parse_args()

    if not args.token:
        print("Informe o token com --token ou pela variável AUTH_TOKEN.")
        return 2

    print(f"Testando {args.url}")
    try:
        asyncio.run(run(args.url, args.token))
    except Exception as exc:  # noqa: BLE001 - mostrar qualquer falha de forma legível
        # o cliente MCP embrulha erros de rede/HTTP em ExceptionGroup; mostra a causa real
        while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
            exc = exc.exceptions[0]
        print(f"  [FALHOU] {type(exc).__name__}: {exc}")
        return 1
    print("Tudo certo!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
