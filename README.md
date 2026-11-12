# 🧠 Second Brain MCP Server

Servidor MCP (**Model Context Protocol**) pessoal projetado para registrar continuamente todo o histórico do seu trabalho, decisões técnicas de arquitetura, resoluções de bugs e estudos.

Ele permite que agentes de IA (como o **Google Antigravity**) acessem suas memórias em tempo real para tomar decisões alinhadas com o seu estilo de código e gerem automaticamente resumos para atualizar seu **LinkedIn, currículo ou portfólio**.

---

## 🏗️ Arquitetura

```
┌─────────────────────────────────┐               ┌────────────────────────────────────────────────────────┐
│   Google Antigravity            │               │ Google Cloud Platform (Sua Conta Pessoal)              │
│   (Seu PC de Trabalho / Casa)   │               │                                                        │
│                                 │  Streamable   │   Cloud Run (FastAPI + MCP Python SDK)                 │
│   mcp_config.json               │     HTTP      │   • Escala para 0 instâncias quando ocioso             │
│   (URL + Bearer Token)          │──────────────>│   • AUTH_TOKEN lido do Secret Manager                  │
│                                 │               │              │                                         │
└─────────────────────────────────┘               │              ▼                                         │
                                                  │   Firestore (Banco NoSQL Nativo GCP)                   │
                                                  │   • Memórias + lixeira (soft delete)                   │
                                                  │   • Dentro do Free Tier (1 GB / 50k leituras/dia)      │
                                                  └────────────────────────────────────────────────────────┘
```

---

## 🛠️ Ferramentas Disponíveis no MCP (Tools)

| Ferramenta | Descrição |
| :--- | :--- |
| `salvar_memoria` | Registra uma nova memória, aprendizado, entrega, snippet ou decisão técnica. |
| `atualizar_memoria` | Atualiza campos de uma memória existente (evita duplicatas quando um aprendizado evolui). |
| `buscar_memorias` | Busca memórias por texto livre, categoria, tag (exata) ou projeto (sem diferenciar maiúsculas). |
| `listar_atividades_recentes` | Recapitula o que você produziu e estudou nos últimos N dias. |
| `obter_memoria_por_id` | Retorna os detalhes completos de um registro pelo UUID. |
| `gerar_resumo_portfolio` | Agrupa projetos e tecnologias dominadas para gerar tópicos de currículo e LinkedIn. |
| `remover_memoria` | Move uma memória para a lixeira (continua recuperável no banco). |

---

## 🚀 Como Testar Localmente

Três níveis, do mais rápido ao mais próximo da produção. Nenhum precisa de conta no GCP.

### Preparação

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env           # Windows: copy .env.example .env
```

### 1. Testes automatizados

SQLite, Firestore simulado em memória e o endpoint MCP de ponta a ponta:

```bash
pytest -q
```

### 2. Servidor local com SQLite + cliente MCP real

```bash
python -m src.main
```

Em outro terminal, o teste de fumaça conecta com o cliente oficial do MCP (o mesmo caminho do Antigravity) e executa salvar → buscar → atualizar → remover:

```bash
python scripts/smoke_test.py --url http://localhost:8080/mcp --token dev-secret-token
```

* Health check: `http://localhost:8080/health`
* Endpoint MCP: `http://localhost:8080/mcp`

### 3. Servidor local com o emulador do Firestore

Testa o backend Firestore de verdade, sem tocar no seu projeto do GCP. Requer Java (JDK 21) e o emulador:

```bash
gcloud components install cloud-firestore-emulator
gcloud emulators firestore start --host-port=localhost:8085
```

No `.env`, troque para o modo Firestore apontando para o emulador:

```env
STORAGE_BACKEND=firestore
FIRESTORE_EMULATOR_HOST=localhost:8085
GCP_PROJECT_ID=demo-second-brain
AUTH_TOKEN=<gere com: python -c "import secrets; print(secrets.token_hex(32))">
```

Suba o servidor e rode o mesmo teste de fumaça com o token novo. As memórias aparecem na UI do emulador (o endereço é exibido no terminal do emulador) e somem quando ele é encerrado.

### Conectar o Antigravity no servidor local

Use `http://localhost:8080/mcp` e o token do `.env` na configuração mostrada em [Conectando ao Antigravity](#-conectando-ao-antigravity).

---

## ☁️ Deploy no Google Cloud Run

### 1. Pré-requisitos
* Conta pessoal no Google Cloud com faturamento ativo (Cloud Run, Firestore e Secret Manager têm cota gratuita).
* CLI do `gcloud` instalada, ou o **Google Cloud Shell** direto no navegador.

### 2. Executar o deploy

* **Linux / Mac / Cloud Shell:**
  ```bash
  chmod +x deploy.sh
  ./deploy.sh
  ```
* **Windows:**
  ```cmd
  deploy.bat
  ```

O script faz tudo de forma idempotente (pode rodar de novo sem problemas):

1. habilita as APIs necessárias;
2. cria o banco **Firestore** em modo nativo, se ainda não existir;
3. cria a service account `second-brain-run`, com acesso só ao Firestore e ao secret;
4. gera um **AUTH_TOKEN** forte e guarda no **Secret Manager** (o token nunca vai para variável de ambiente em texto puro nem aparece no terminal);
5. faz o build com o **Cloud Build** e o deploy no Cloud Run.

Para gerar um token novo: `ROTATE_TOKEN=1 ./deploy.sh` (ou `deploy.bat rotate`).

### 3. Pegar a URL e o token e validar

```bash
gcloud run services describe second-brain-mcp --region us-central1 --format='value(status.url)'
gcloud secrets versions access latest --secret=second-brain-auth-token

python scripts/smoke_test.py --url https://<seu-servico>.run.app/mcp --token <token>
```

> [!NOTE]
> O serviço é público na rede (`--allow-unauthenticated`), mas todas as rotas, exceto `/` e `/health`, exigem o Bearer token. Em modo `firestore`, o servidor **se recusa a subir** se o `AUTH_TOKEN` estiver ausente, for o token padrão ou tiver menos de 32 caracteres.

---

## 🔁 Deploy Automático (GitHub Actions)

O workflow `.github/workflows/deploy.yml` roda os testes em todo push e PR, e faz o deploy quando há push na `main`. A autenticação usa **Workload Identity Federation**, sem chave JSON de service account guardada no GitHub.

Configuração única (substitua os valores):

```bash
PROJECT_ID=meu-projeto
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
REPO=LeoGR22/second-brain
DEPLOY_SA=github-deployer@$PROJECT_ID.iam.gserviceaccount.com

# Service account usada pelo GitHub para fazer o deploy
gcloud iam service-accounts create github-deployer --display-name="GitHub deployer"
for role in roles/run.sourceDeveloper roles/iam.serviceAccountUser roles/serviceusage.serviceUsageConsumer; do
  gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:$DEPLOY_SA" --role=$role --condition=None
done

# Pool e provider OIDC restritos a este repositório
gcloud iam workload-identity-pools create github --location=global
gcloud iam workload-identity-pools providers create-oidc github --location=global \
  --workload-identity-pool=github \
  --issuer-uri=https://token.actions.githubusercontent.com \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='$REPO'"

gcloud iam service-accounts add-iam-policy-binding $DEPLOY_SA \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$REPO"
```

Secrets do repositório (Settings → Secrets and variables → Actions):

| Secret | Valor |
| :--- | :--- |
| `GCP_PROJECT_ID` | ID do projeto |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github/providers/github` |
| `GCP_DEPLOY_SA` | `github-deployer@<PROJECT_ID>.iam.gserviceaccount.com` |

> Rode o `deploy.sh` uma vez antes do primeiro deploy pelo GitHub: é ele que cria o Firestore, o secret e a service account de runtime.

---

## 🔌 Conectando ao Antigravity

Abra o arquivo de configuração de MCPs: `%USERPROFILE%\.gemini\config\mcp_config.json` (Windows) ou `~/.gemini/config/mcp_config.json`.

```json
{
  "mcpServers": {
    "second-brain": {
      "url": "https://second-brain-mcp-xyz123-uc.a.run.app/mcp",
      "headers": {
        "Authorization": "Bearer SEU_TOKEN_DO_SECRET_MANAGER"
      }
    }
  }
}
```

> [!TIP]
> Para desenvolvimento local, use `http://localhost:8080/mcp` e o token do seu `.env`.

---

## 💬 Exemplos de Uso com o Agente

* **Salvar aprendizados:**
  > *"Acabamos de resolver o erro de lifespan ao montar o MCP dentro do FastAPI. Salve essa solução no meu segundo cérebro com as tags mcp, fastapi, python."*

* **Evoluir uma memória:**
  > *"Aquela solução do lifespan mudou: agora o app MCP é montado na raiz. Atualize a memória."*

* **Consultar histórico:**
  > *"Como eu configurei o Secret Manager no deploy do Cloud Run da última vez? Consulte minhas memórias."*

* **Atualizar perfil / LinkedIn / portfólio:**
  > *"Gere um resumo para o meu LinkedIn com as principais tecnologias e entregas que realizei no último mês baseado nas minhas memórias."*

---

## 📝 Detalhes de Implementação

* **Mesmo comportamento nos dois backends:** tags normalizadas, filtro de projeto sem diferenciar maiúsculas, tag com correspondência exata e soft delete. Os testes de storage rodam a mesma suíte contra SQLite e contra um Firestore simulado.
* **Firestore sem índices compostos:** as consultas usam só filtros de igualdade; a ordenação por data e a busca textual são feitas em memória sobre até `FIRESTORE_MAX_SCAN` documentos (padrão 2000), adequado para uso pessoal.
* **Próximo passo planejado:** busca semântica com embeddings do Gemini e vector search do Firestore.
