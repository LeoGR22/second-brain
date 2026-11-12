import contextlib
import hmac
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.config import settings
from src.server import mcp

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("second-brain")

PUBLIC_PATHS = {"/", "/health"}


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # O transporte streamable HTTP do MCP precisa do session manager rodando.
    # Apps montados dentro do FastAPI não têm o próprio lifespan executado,
    # então ele é iniciado aqui.
    async with mcp.session_manager.run():
        logger.info("MCP session manager iniciado (storage=%s)", settings.storage_backend)
        yield


app = FastAPI(
    title="Second Brain MCP Server",
    description="Servidor MCP pessoal para gerenciar memórias, aprendizados, decisões técnicas e histórico profissional.",
    version="1.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Endpoints públicos liberados para monitoramento do Cloud Run
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)

    # Validação do cabeçalho 'Authorization: Bearer <AUTH_TOKEN>'
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        logger.warning("Requisição sem cabeçalho Authorization para %s", request.url.path)
        return JSONResponse(
            status_code=401,
            content={"detail": "Cabeçalho de autorização ausente ou malformatado. Formato esperado: 'Authorization: Bearer <token>'"},
        )

    token = auth_header.split(" ", 1)[1].strip()
    # compare_digest evita ataques de timing na comparação do token
    if not hmac.compare_digest(token.encode(), settings.auth_token.encode()):
        logger.warning("Tentativa de acesso com token inválido para %s", request.url.path)
        return JSONResponse(status_code=403, content={"detail": "Token inválido. Acesso não autorizado."})

    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "healthy", "service": "second-brain-mcp", "storage": settings.storage_backend}


@app.get("/")
def root():
    return {"service": "Second Brain MCP Server", "status": "online", "mcp_endpoint": "/mcp"}


# O app MCP já expõe a rota /mcp (streamable_http_path), então é montado na raiz,
# depois das rotas acima. Se a montagem falhar, a aplicação não deve subir.
app.mount("/", mcp.streamable_http_app())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host=settings.host, port=settings.port, reload=True)
