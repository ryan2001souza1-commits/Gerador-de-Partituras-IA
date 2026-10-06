# Worker na RunPod (guia de hospedagem, sem deploy executado)

Este documento descreve como publicar o worker **posteriormente** na
RunPod (ou qualquer host Docker com GPU NVIDIA). Nada aqui executa
nada sozinho; nenhum secret real está neste arquivo.

## 1. Pré-requisitos

- Imagem `gpi-worker` construída a partir de `worker/Dockerfile`
  (ou publicada num registry: Docker Hub, GHCR, etc.).
- Uma conta RunPod com acesso a GPU (qualquer modelo NVIDIA com
  CUDA 12.1+; sem GPU o worker cai para CPU sozinho).
- O valor de `WORKER_WEBHOOK_SECRET` (o MESMO configurado na API —
  cadastre-o nas variáveis de ambiente do pod, nunca no código).

## 2. Criar a infraestrutura (quando for a hora)

1. RunPod → Pods → Deploy (ou template a partir da imagem).
2. Imagem: a publicada (`.../gpi-worker:gpu` para GPU).
3. Tipo de GPU: qualquer NVIDIA disponível (ex. RTX 3090/4090, A40).
4. Porta HTTP: expor a porta do contêiner (padrão `8001`; a RunPod
   injeta `PORT` — o worker respeita `PORT` automaticamente).
5. Volume/cache (recomendado): montar um volume persistente em
   `/home/appuser/.cache` para reaproveitar os pesos (PANNs ~313 MB
   + Demucs) entre reinícios. Sem volume, os modelos baixam de novo
   no primeiro job (funciona, só demora mais).
6. Variáveis de ambiente do pod:
   - `WORKER_WEBHOOK_SECRET=<segredo compartilhado com a API>`
   - `PORT=<porta exposta>` (ou deixe a RunPod injetar)
   - Opcional: `AUDIO_MAX_BYTES`, `DEMUCS_MODEL`, `DEMUCS_DEVICE`
     (`auto` detecta CUDA sozinho), `DEMUCS_TIMEOUT_S`.
7. Iniciar o pod e anotar a URL pública, ex.:
   `https://<id>-8001.proxy.runpod.net`.

## 3. Variáveis necessárias (resumo)

| Variável | Obrigatória | Exemplo |
|---|---|---|
| `WORKER_WEBHOOK_SECRET` | sim | *(somente no provedor)* |
| `PORT` | não (padrão 8001) | `8000` |
| `AUDIO_TMP_DIR` | não | `/tmp/gpi` |
| `AUDIO_MAX_BYTES` | não | `26214400` |
| `DEMUCS_MODEL` / `DEMUCS_DEVICE` / `DEMUCS_TIMEOUT_S` | não | `htdemucs` / `auto` / `600` |

Ver `worker/.env.example` (só nomes, sem valores).

## 4. URL pública e testes

Com o pod no ar e a porta exposta:

```bash
BASE=https://<id>-8001.proxy.runpod.net

# Saúde (sem autenticação; mostra device sem segredos)
curl $BASE/health
# → {"ok":true,"service":"audio-worker","device":"cuda"}

# Aceite de job (resposta imediata; pesado roda em background)
curl -X POST $BASE/jobs/transcribe \
  -H 'Content-Type: application/json' \
  -d '{"job_id":"teste-123","audio_source_id":"src-1",
       "audio_url":"https://exemplo.test/a.wav",
       "callback_url":"https://sua-api.test/api/transcription/webhook"}'
# → {"accepted":true,"job_id":"teste-123","status":"queued"}
```

## 5. Conectar ao Vercel (etapa futura, sem executar agora)

Com a URL pública validada, configurar na Vercel a variável
`WORKER_BASE_URL` com a base do worker (sem barra final), ex.
`https://<id>-8001.proxy.runpod.net`. O dispatch PHP passa então a
enviar os jobs para o worker real em vez do dry-run.

## 6. Notas de segurança

- O worker nunca recebe segredos no JSON: o `WORKER_WEBHOOK_SECRET`
  vive só nas variáveis de ambiente dos dois lados.
- SSRF: `localhost`, IPs privados, metadata endpoints (`169.254…`)
  e `file://` são recusados no download e no webhook.
- Logs registram só `job_id` e host redactado — nunca URLs
  completas, tokens ou segredos.

## 7. Publicação da imagem (etapa futura, sem executar agora)

Quando for a hora de publicar (NÃO executar nesta fase):

a) **Construir a imagem** (CPU; para GPU trocar os build args
   documentados no topo do `Dockerfile`):

```bash
docker build -t <REGISTRY>/<NAMESPACE>/gpi-worker:<TAG> ./worker
```

b) **Autenticar no registry** (exemplos: Docker Hub, GHCR ou outro
   registry compatível — sem exigir nenhum específico):

```bash
docker login <REGISTRY>
```

c) **Aplicar a tag** (se ainda não aplicada no build):

```bash
docker tag gpi-worker:cpu <REGISTRY>/<NAMESPACE>/gpi-worker:<TAG>
```

d) **Push**:

```bash
docker push <REGISTRY>/<NAMESPACE>/gpi-worker:<TAG>
```

e) **Usar no RunPod**: na criação do pod, informar a referência
   completa `<REGISTRY>/<NAMESPACE>/gpi-worker:<TAG>` como imagem,
   seguindo as seções 2–4 acima (porta, GPU, volume, variáveis).

Para GPU, o mesmo `Dockerfile` serve via build args
(`BASE_IMAGE`, `TORCH_INDEX_URL`, `TORCH_VERSION` — ver cabeçalho
do arquivo); o fallback CPU continua funcionando sem GPU.

## 8. GHCR — Publicação da imagem (etapa futura, sem executar agora)

Fluxo futuro para publicar no GitHub Container Registry
(`ghcr.io`). Nenhum passo abaixo foi executado nesta fase.

a) **Autenticar no GHCR** (em máquina com Docker, nunca nesta
   sem Docker; nunca colar tokens em arquivos do repo):

```bash
docker login ghcr.io
```

b) **Construir a imagem** (CPU; GPU via build args do `Dockerfile`):

```bash
docker build -t ghcr.io/<OWNER>/<IMAGE>:<TAG> ./worker
```

c) **Aplicar tag** (se ainda não aplicada no build):

```bash
docker tag gpi-worker:cpu ghcr.io/<OWNER>/<IMAGE>:<TAG>
```

d) **Push**:

```bash
docker push ghcr.io/<OWNER>/<IMAGE>:<TAG>
```

e) **Privacidade**: por padrão os pacotes GHCR nascem privados —
   ou torne o pacote público nas configurações do pacote, ou
   cadastre as credenciais de leitura no RunPod para imagem
   privada. Em ambos os casos, `WORKER_WEBHOOK_SECRET` continua
   sendo variável de ambiente em runtime, nunca camada da imagem.

f) **Usar no RunPod**: informar a referência completa
   `ghcr.io/<OWNER>/<IMAGE>:<TAG>` como imagem do pod, seguindo
   as seções 2–4 acima.

### Estratégia de tags (recomendada)

- `latest`: só para desenvolvimento/uso manual (mutável).
- Tag imutável para produção, ex. `v1.0.0` ou `2026.10.06-1`.
- O RunPod de produção deve fixar a tag imutável, nunca depender
  só de `latest` (que pode mudar sob os pés do pod em restarts).

### Garantias verificadas

- Nenhum secret entra na imagem (`.dockerignore` barra `.env*`,
  `*.pth`, modelos, caches, venvs e temporários).
- `WORKER_WEBHOOK_SECRET` só em runtime (env do pod + env da API).
- `SUPABASE_SERVICE_ROLE_KEY` não existe no worker.
- Nenhuma API key NVIDIA ou de provedor no `Dockerfile`.

## 9. GitHub Actions → GHCR (fluxo preferido, sem executar agora)

```
GitHub repository
↓ (manual via Actions, ou release publicada — nunca push em main)
GitHub Actions (.github/workflows/worker-image.yml)
↓ (build CPU ou GPU + cache BuildKit)
GHCR (ghcr.io/ryan2001souza1-commits/gerador-de-partituras-ia-worker)
↓
RunPod (imagem fixada por tag imutável)
```

Para publicar, abra a aba **Actions** do repositório no GitHub,
selecione **worker-image** e clique em **Run workflow**, escolhendo
`variant: cpu` (padrão) ou `gpu`, e opcionalmente uma `tag` extra.
Releases publicadas geram também a tag da versão. Em produção,
fixe a tag imutável (ex. `v1.0.0`), nunca só `latest`.

Autenticação usa o `GITHUB_TOKEN` nativo do Actions (permissões
`contents: read` + `packages: write`); nenhum PAT ou secret vai
para o código. Segredos de runtime (`WORKER_WEBHOOK_SECRET`, etc.)
continuam só nas variáveis do pod.
