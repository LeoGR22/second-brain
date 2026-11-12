import json
from typing import List, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from src.storage import get_storage

# Inicializa o servidor FastMCP
mcp = FastMCP(
    "SecondBrain",
    instructions=(
        "Servidor MCP de Memória Pessoal (Segundo Cérebro). Armazena e recupera aprendizados, "
        "decisões técnicas, histórico de trabalho e realiza resumos de portfólio. "
        "Antes de salvar algo novo, busque se já existe uma memória parecida e prefira atualizá-la."
    ),
    stateless_http=True,
    # Rota final do endpoint (o app é montado na raiz do FastAPI)
    streamable_http_path="/mcp",
    # A proteção contra DNS rebinding do SDK só aceita Host localhost por padrão e
    # rejeitaria o domínio *.run.app com 421. O acesso já é protegido pelo Bearer token.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

storage = get_storage()


def _format_memory(index: int, r: dict) -> str:
    tags_str = ", ".join(r.get("tags", [])) or "nenhuma"
    proj = f" | Projeto: {r.get('projeto')}" if r.get("projeto") else ""
    return (
        f"--- [Memória #{index}] ---\n"
        f"ID: {r.get('id')}\n"
        f"Título: {r.get('titulo')}\n"
        f"Categoria: {r.get('categoria')}{proj}\n"
        f"Tags: [{tags_str}]\n"
        f"Data: {r.get('created_at', '')[:10]}\n"
        f"Conteúdo:\n{r.get('conteudo')}\n"
    )


@mcp.tool()
def salvar_memoria(
    titulo: str,
    conteudo: str,
    categoria: str = "geral",
    tags: Optional[List[str]] = None,
    projeto: Optional[str] = None,
    url_referencia: Optional[str] = None,
) -> str:
    """Salva uma nova memória, aprendizado, decisão de arquitetura, solução de bug ou entrega técnica.

    Args:
        titulo: Título objetivo da memória (ex: 'Cache de dependências no build Docker')
        conteudo: Detalhes, código, explicação do erro, passos tomados ou aprendizado
        categoria: Categoria ('estudo', 'trabalho', 'bugfix', 'arquitetura', 'portfolio', 'snippet', 'geral')
        tags: Lista de tags para categorização (ex: ['docker', 'python', 'ci-cd'])
        projeto: Nome do projeto onde isso ocorreu (ex: 'second-brain', 'contract-extractor')
        url_referencia: Link opcional de referência (PR, issue, doc, commit)
    """
    mem = storage.save_memory(
        titulo=titulo,
        conteudo=conteudo,
        categoria=categoria,
        tags=tags,
        projeto=projeto,
        url_referencia=url_referencia,
    )
    return f"Memória salva com sucesso! ID: {mem['id']}\nTítulo: {mem['titulo']}"


@mcp.tool()
def atualizar_memoria(
    memoria_id: str,
    titulo: Optional[str] = None,
    conteudo: Optional[str] = None,
    categoria: Optional[str] = None,
    tags: Optional[List[str]] = None,
    projeto: Optional[str] = None,
    url_referencia: Optional[str] = None,
) -> str:
    """Atualiza uma memória existente. Só os campos informados são alterados.

    Use quando um aprendizado evoluir (ex: a solução de um bug mudou) em vez de criar uma memória duplicada.
    Para acrescentar informação, busque a memória, junte o conteúdo antigo com o novo e envie o resultado.

    Args:
        memoria_id: UUID da memória
        titulo: Novo título
        conteudo: Novo conteúdo (substitui o anterior)
        categoria: Nova categoria
        tags: Nova lista de tags (substitui a anterior)
        projeto: Novo projeto
        url_referencia: Novo link de referência
    """
    mem = storage.update_memory(
        memoria_id,
        titulo=titulo,
        conteudo=conteudo,
        categoria=categoria,
        tags=tags,
        projeto=projeto,
        url_referencia=url_referencia,
    )
    if mem is None:
        return f"Memória com ID '{memoria_id}' não encontrada."
    return f"Memória atualizada com sucesso! ID: {mem['id']}\nTítulo: {mem['titulo']}"


@mcp.tool()
def buscar_memorias(
    busca: Optional[str] = None,
    categoria: Optional[str] = None,
    tag: Optional[str] = None,
    projeto: Optional[str] = None,
    limite: int = 10,
) -> str:
    """Busca memórias cadastradas por termo livre, categoria, tag ou projeto.

    Args:
        busca: Termo textual para procurar no título ou no conteúdo
        categoria: Filtrar por categoria específica
        tag: Filtrar por uma tag específica (correspondência exata)
        projeto: Filtrar por projeto específico (ignora maiúsculas/minúsculas)
        limite: Quantidade máxima de resultados (padrão: 10)
    """
    results = storage.search_memories(query=busca, categoria=categoria, tag=tag, projeto=projeto, limit=limite)
    if not results:
        return "Nenhuma memória encontrada para os filtros informados."

    output = [f"Encontradas {len(results)} memórias:\n"]
    output += [_format_memory(i, r) for i, r in enumerate(results, 1)]
    return "\n".join(output)


@mcp.tool()
def listar_atividades_recentes(dias: int = 7, limite: int = 15) -> str:
    """Recapitula as memórias e atividades registradas nos últimos dias.
    Excelente para iniciar o dia sabendo o que foi feito recentemente.

    Args:
        dias: Quantidade de dias no passado a considerar (padrão: 7)
        limite: Quantidade máxima de registros (padrão: 15)
    """
    results = storage.list_recent(days=dias, limit=limite)
    if not results:
        return f"Nenhuma atividade registrada nos últimos {dias} dias."

    output = [f"Atividades dos últimos {dias} dias ({len(results)} registros):\n"]
    for r in results:
        proj = f" [{r.get('projeto')}]" if r.get("projeto") else ""
        output.append(f"• {r.get('created_at', '')[:10]}{proj} - {r.get('titulo')} ({r.get('categoria')})")
    return "\n".join(output)


@mcp.tool()
def obter_memoria_por_id(memoria_id: str) -> str:
    """Busca o detalhe completo de uma memória específica através de seu ID único.

    Args:
        memoria_id: UUID da memória
    """
    mem = storage.get_memory(memoria_id)
    if not mem:
        return f"Memória com ID '{memoria_id}' não encontrada."
    return json.dumps(mem, indent=2, ensure_ascii=False)


@mcp.tool()
def remover_memoria(memoria_id: str) -> str:
    """Move uma memória para a lixeira pelo ID. Ela deixa de aparecer nas buscas,
    mas continua recuperável diretamente no banco.

    Só use quando o usuário pedir explicitamente para remover.

    Args:
        memoria_id: UUID da memória a ser removida
    """
    if storage.delete_memory(memoria_id):
        return f"Memória '{memoria_id}' movida para a lixeira."
    return f"Memória '{memoria_id}' não encontrada para remoção."


@mcp.tool()
def gerar_resumo_portfolio(foco: Optional[str] = None, limite: int = 20) -> str:
    """Agrupa competências, tecnologias dominadas, projetos e destaques para atualização de LinkedIn, currículo ou portfólio.

    Args:
        foco: Palavra-chave opcional para filtrar os destaques (ex: 'backend', 'cloud', 'llm')
        limite: Quantidade de memórias analisadas
    """
    summary = storage.portfolio_summary(focus=foco, limit=limite)

    skills = ", ".join(f"{k} ({v}x)" for k, v in summary["principais_skills_e_tags"])
    projetos = ", ".join(f"{k} ({v}x)" for k, v in summary["projetos_envolvidos"])

    output = [
        "=== RESUMO PARA PERFIL / PORTFÓLIO ===\n",
        f"Memórias analisadas: {summary['total_analisado']}",
        f"Tecnologias mais praticadas: {skills or 'Nenhuma'}",
        f"Projetos com contribuições: {projetos or 'Nenhum'}\n",
        "Principais Entregas e Destaques Técnicos:",
    ]
    for d in summary["destaques_para_curriculo"]:
        output.append(
            f"• [{d['data']}] {d['titulo']}"
            + (f" ({d['projeto']})" if d.get("projeto") else "")
            + f"\n  Resumo: {d['resumo']}"
        )
    return "\n".join(output)
