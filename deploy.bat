@echo off
setlocal
REM ==============================================================================
REM Deploy do Second Brain MCP no Google Cloud Run (Windows)
REM
REM - Gera o AUTH_TOKEN e guarda no Secret Manager (nunca em variavel de ambiente
REM   em texto puro nem impresso no terminal).
REM - Cria uma service account dedicada com acesso so ao Firestore e ao secret.
REM - Cria o banco Firestore (modo nativo) se ainda nao existir.
REM
REM Uso:   deploy.bat              deploy normal
REM        deploy.bat rotate       gera um token novo antes do deploy
REM        deploy.bat terms        redefine os termos bloqueados
REM ==============================================================================

set SERVICE_NAME=second-brain-mcp
set REGION=us-central1
set SECRET_NAME=second-brain-auth-token
set TERMS_SECRET_NAME=second-brain-blocked-terms
set RUNTIME_SA_NAME=second-brain-run
set COLLECTION=second_brain_memories
set TOKEN_FILE=%TEMP%\second_brain_token.txt
set TERMS_FILE=%TEMP%\second_brain_terms.txt

set /p GCP_PROJECT="Digite o ID do seu projeto GCP pessoal: "
if "%GCP_PROJECT%"=="" (
    echo Erro: o ID do projeto GCP e obrigatorio.
    exit /b 1
)
set SA_EMAIL=%RUNTIME_SA_NAME%@%GCP_PROJECT%.iam.gserviceaccount.com

echo.
echo [1/7] Configurando projeto ativo no gcloud...
call gcloud config set project %GCP_PROJECT% >nul
if errorlevel 1 goto :error

echo [2/7] Habilitando APIs necessarias...
call gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com firestore.googleapis.com secretmanager.googleapis.com
if errorlevel 1 goto :error

echo [3/7] Garantindo o banco Firestore (modo nativo)...
call gcloud firestore databases describe --database="(default)" >nul 2>&1
if errorlevel 1 (
    call gcloud firestore databases create --database="(default)" --location=%REGION% --type=firestore-native
    if errorlevel 1 goto :error
)

echo [4/7] Garantindo a service account do Cloud Run...
call gcloud iam service-accounts describe %SA_EMAIL% >nul 2>&1
if errorlevel 1 (
    call gcloud iam service-accounts create %RUNTIME_SA_NAME% --display-name="Second Brain MCP (Cloud Run)"
    if errorlevel 1 goto :error
)
call gcloud projects add-iam-policy-binding %GCP_PROJECT% --member="serviceAccount:%SA_EMAIL%" --role="roles/datastore.user" --condition=None >nul
if errorlevel 1 goto :error

for /f "usebackq delims=" %%N in (`gcloud projects describe %GCP_PROJECT% --format^="value(projectNumber)"`) do set PROJECT_NUMBER=%%N
call gcloud projects add-iam-policy-binding %GCP_PROJECT% --member="serviceAccount:%PROJECT_NUMBER%-compute@developer.gserviceaccount.com" --role="roles/run.builder" --condition=None >nul
if errorlevel 1 goto :error

echo [5/7] Garantindo o AUTH_TOKEN no Secret Manager...
call gcloud secrets describe %SECRET_NAME% >nul 2>&1
if errorlevel 1 (
    call :generate_token
    call gcloud secrets create %SECRET_NAME% --replication-policy=automatic --data-file="%TOKEN_FILE%"
    if errorlevel 1 goto :error
    del /q "%TOKEN_FILE%"
    echo       Token novo gerado.
) else if /i "%~1"=="rotate" (
    call :generate_token
    call gcloud secrets versions add %SECRET_NAME% --data-file="%TOKEN_FILE%"
    if errorlevel 1 goto :error
    del /q "%TOKEN_FILE%"
    echo       Token rotacionado. Atualize o cliente MCP com o novo valor.
) else (
    echo       Usando o token ja existente.
)
call gcloud secrets add-iam-policy-binding %SECRET_NAME% --member="serviceAccount:%SA_EMAIL%" --role="roles/secretmanager.secretAccessor" >nul
if errorlevel 1 goto :error

echo [6/7] Termos bloqueados no Secret Manager...
set TERMS_EXISTS=0
call gcloud secrets describe %TERMS_SECRET_NAME% >nul 2>&1
if not errorlevel 1 set TERMS_EXISTS=1
set ASK_TERMS=0
if "%TERMS_EXISTS%"=="0" set ASK_TERMS=1
if /i "%~1"=="terms" set ASK_TERMS=1
if "%ASK_TERMS%"=="0" goto :terms_done
set BLOCKED_TERMS=
set /p BLOCKED_TERMS="      Termos bloqueados, separados por virgula (Enter para pular): "
if "%BLOCKED_TERMS%"=="" goto :terms_done
<nul set /p ="%BLOCKED_TERMS%" > "%TERMS_FILE%"
if "%TERMS_EXISTS%"=="0" (
    call gcloud secrets create %TERMS_SECRET_NAME% --replication-policy=automatic --data-file="%TERMS_FILE%"
) else (
    call gcloud secrets versions add %TERMS_SECRET_NAME% --data-file="%TERMS_FILE%"
)
if errorlevel 1 goto :error
del /q "%TERMS_FILE%"
set TERMS_EXISTS=1
:terms_done
set SECRETS=AUTH_TOKEN=%SECRET_NAME%:latest
if "%TERMS_EXISTS%"=="0" goto :no_terms
call gcloud secrets add-iam-policy-binding %TERMS_SECRET_NAME% --member="serviceAccount:%SA_EMAIL%" --role="roles/secretmanager.secretAccessor" >nul
if errorlevel 1 goto :error
set SECRETS=%SECRETS%,BLOCKED_TERMS=%TERMS_SECRET_NAME%:latest
echo       Termos bloqueados ativos.
goto :deploy
:no_terms
echo       Sem termos bloqueados (so a deteccao de credenciais fica ativa).
:deploy

echo [7/7] Build e deploy no Cloud Run...
call gcloud run deploy %SERVICE_NAME% ^
    --source . ^
    --region %REGION% ^
    --service-account %SA_EMAIL% ^
    --allow-unauthenticated ^
    --min-instances 0 ^
    --max-instances 1 ^
    --memory 512Mi ^
    --cpu 1 ^
    --set-secrets "%SECRETS%" ^
    --set-env-vars "STORAGE_BACKEND=firestore,GCP_PROJECT_ID=%GCP_PROJECT%,FIRESTORE_COLLECTION=%COLLECTION%"
if errorlevel 1 goto :error

echo.
echo ==============================================================================
echo Deploy finalizado! Copie a URL do servico exibida acima e acrescente /mcp.
echo Para ver o token (nao e impresso aqui):
echo   gcloud secrets versions access latest --secret=%SECRET_NAME%
echo ==============================================================================
endlocal
exit /b 0

:generate_token
REM 32 bytes aleatorios em hexadecimal, gravados sem quebra de linha
powershell -NoProfile -Command "$b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); $t = -join ($b | ForEach-Object { $_.ToString('x2') }); Set-Content -NoNewline -Path $env:TEMP\second_brain_token.txt -Value $t"
exit /b 0

:error
echo.
echo Erro durante o deploy. Veja a mensagem acima.
if exist "%TOKEN_FILE%" del /q "%TOKEN_FILE%"
if exist "%TERMS_FILE%" del /q "%TERMS_FILE%"
endlocal
exit /b 1
