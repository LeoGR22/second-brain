#!/usr/bin/env bash
# ==============================================================================
# Deploy do Second Brain MCP no Google Cloud Run (Linux/Mac/Cloud Shell)
#
# - Gera o AUTH_TOKEN e guarda no Secret Manager (nunca em variável de ambiente
#   em texto puro nem impresso no terminal).
# - Cria uma service account dedicada com acesso só ao Firestore e ao secret.
# - Cria o banco Firestore (modo nativo) se ainda não existir.
#
# Uso:   ./deploy.sh                          # deploy normal
#        ROTATE_TOKEN=1 ./deploy.sh           # gera um token novo antes do deploy
#        UPDATE_BLOCKED_TERMS=1 ./deploy.sh   # redefine os termos bloqueados
# ==============================================================================
set -euo pipefail

SERVICE_NAME="second-brain-mcp"
REGION="${REGION:-us-central1}"
SECRET_NAME="second-brain-auth-token"
TERMS_SECRET_NAME="second-brain-blocked-terms"
RUNTIME_SA_NAME="second-brain-run"
COLLECTION="second_brain_memories"

read -rp "Digite o ID do seu projeto GCP pessoal: " GCP_PROJECT
if [ -z "$GCP_PROJECT" ]; then
    echo "Erro: o ID do projeto GCP é obrigatório."
    exit 1
fi
SA_EMAIL="${RUNTIME_SA_NAME}@${GCP_PROJECT}.iam.gserviceaccount.com"

echo "[1/7] Configurando projeto ativo no gcloud..."
gcloud config set project "$GCP_PROJECT" >/dev/null

echo "[2/7] Habilitando APIs necessárias..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
    firestore.googleapis.com secretmanager.googleapis.com

echo "[3/7] Garantindo o banco Firestore (modo nativo)..."
if ! gcloud firestore databases describe --database="(default)" >/dev/null 2>&1; then
    gcloud firestore databases create --database="(default)" --location="$REGION" --type=firestore-native
fi

echo "[4/7] Garantindo a service account do Cloud Run..."
if ! gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$RUNTIME_SA_NAME" --display-name="Second Brain MCP (Cloud Run)"
fi
gcloud projects add-iam-policy-binding "$GCP_PROJECT" \
    --member="serviceAccount:$SA_EMAIL" --role="roles/datastore.user" --condition=None >/dev/null

PROJECT_NUMBER=$(gcloud projects describe "$GCP_PROJECT" --format='value(projectNumber)')
gcloud projects add-iam-policy-binding "$GCP_PROJECT" \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/run.builder" --condition=None >/dev/null

echo "[5/7] Garantindo o AUTH_TOKEN no Secret Manager..."
if ! gcloud secrets describe "$SECRET_NAME" >/dev/null 2>&1; then
    openssl rand -hex 32 | tr -d '\n' | \
        gcloud secrets create "$SECRET_NAME" --replication-policy=automatic --data-file=-
    echo "      Token novo gerado."
elif [ "${ROTATE_TOKEN:-0}" = "1" ]; then
    openssl rand -hex 32 | tr -d '\n' | gcloud secrets versions add "$SECRET_NAME" --data-file=-
    echo "      Token rotacionado. Atualize o cliente MCP com o novo valor."
else
    echo "      Usando o token já existente."
fi
gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
    --member="serviceAccount:$SA_EMAIL" --role="roles/secretmanager.secretAccessor" >/dev/null

echo "[6/7] Termos bloqueados no Secret Manager..."
TERMS_EXISTS=0
gcloud secrets describe "$TERMS_SECRET_NAME" >/dev/null 2>&1 && TERMS_EXISTS=1
if [ "$TERMS_EXISTS" = "0" ] || [ "${UPDATE_BLOCKED_TERMS:-0}" = "1" ]; then
    read -rp "      Termos bloqueados, separados por vírgula (Enter para pular): " BLOCKED_TERMS
    if [ -n "$BLOCKED_TERMS" ]; then
        if [ "$TERMS_EXISTS" = "0" ]; then
            printf '%s' "$BLOCKED_TERMS" | \
                gcloud secrets create "$TERMS_SECRET_NAME" --replication-policy=automatic --data-file=-
            TERMS_EXISTS=1
        else
            printf '%s' "$BLOCKED_TERMS" | gcloud secrets versions add "$TERMS_SECRET_NAME" --data-file=-
        fi
    fi
fi
SECRETS="AUTH_TOKEN=${SECRET_NAME}:latest"
if [ "$TERMS_EXISTS" = "1" ]; then
    gcloud secrets add-iam-policy-binding "$TERMS_SECRET_NAME" \
        --member="serviceAccount:$SA_EMAIL" --role="roles/secretmanager.secretAccessor" >/dev/null
    SECRETS="${SECRETS},BLOCKED_TERMS=${TERMS_SECRET_NAME}:latest"
    echo "      Termos bloqueados ativos."
else
    echo "      Sem termos bloqueados (só a detecção de credenciais fica ativa)."
fi

echo "[7/7] Build e deploy no Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
    --source . \
    --region "$REGION" \
    --service-account "$SA_EMAIL" \
    --allow-unauthenticated \
    --min-instances 0 \
    --max-instances 1 \
    --memory 512Mi \
    --cpu 1 \
    --set-secrets "$SECRETS" \
    --set-env-vars "STORAGE_BACKEND=firestore,GCP_PROJECT_ID=${GCP_PROJECT},FIRESTORE_COLLECTION=${COLLECTION}"

URL=$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format='value(status.url)')
echo "=============================================================================="
echo "Deploy finalizado!"
echo "Endpoint MCP: ${URL}/mcp"
echo "Para ver o token (não é impresso aqui):"
echo "  gcloud secrets versions access latest --secret=${SECRET_NAME}"
echo "=============================================================================="
