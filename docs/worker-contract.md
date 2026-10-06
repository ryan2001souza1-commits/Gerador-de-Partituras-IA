# Contrato do Worker de Transcrição (FASE 1 — fundação)

Este documento define o contrato entre a API (Vercel/PHP) e o futuro
worker externo de DSP. **O worker ainda não existe** — nada aqui é
executado nesta fase. Nenhum segredo está neste arquivo.

## Autenticação

Toda chamada do worker usa o segredo compartilhado `WORKER_WEBHOOK_SECRET`
(somente servidor, nunca no frontend):

- Webhook: header `X-Webhook-Secret: <segredo>` (comparação em tempo
  constante; sem segredo válido → `401`, sem distinguir configuração).
- Download do áudio: `GET /api/audio/signed-url.php?source_id={uuid}`
  com o mesmo header → responde `{success, url, expires_in}` (URL expira
  em ~120s; nunca permanente).

## Entrada futura (worker recebe)

```json
{
  "job_id": "uuid-do-job",
  "audio_source_id": "uuid-do-audio",
  "signed_audio_url": "https://...?token=... (expira em ~120s)",
  "callback_url": "https://gerador-de-partituras-ia.vercel.app/api/transcription/webhook",
  "callback_token": "segredo compartilhado (header X-Webhook-Secret)"
}
```

## Saída futura (worker retorna via webhook)

`POST /api/transcription/webhook` com `X-Webhook-Secret`:

```json
{
  "job_id": "uuid-do-job",
  "status": "queued|processing|completed|failed",
  "progress": 0,
  "stage": "downloading|decoding|analyzing|separating|detecting_instruments|extracting_notes|quantizing|building_score|refining_ai|validating|completed|failed",
  "error_code": null,
  "error_message": null,
  "worker_job_id": null
}
```

Campos `analysis`, `tracks` e `artifacts` serão definidos na FASE 4
(análise real). Até lá, o webhook aceita e persiste somente os campos
acima; `progress` é limitado a 0–100; transições de `status`/`stage`
fora do vocabulário retornam `400`.

## Estados e estágios

Jobs: `pending → queued → processing → completed|failed|cancelled`.
Stages preparados (usados a partir da FASE 4): `queued`, `downloading`,
`decoding`, `analyzing`, `separating`, `detecting_instruments`,
`extracting_notes`, `quantizing`, `building_score`, `refining_ai`,
`validating`, `completed`, `failed`. Nesta fase o sistema opera com
`queued`, `processing`, `completed` e `failed`.

## Segurança e limites

- Bucket privado, objetos em `{user_id}/{uuid}/original.{ext}` (UUID,
  nunca o nome original); MIME validado por conteúdo; teto de tamanho
  via `AUDIO_MAX_SIZE_MB`; cota de 20 uploads/dia por usuário.
- `audio_sources.status` espelha o job (`processing|completed|failed`).
- Nenhuma chave (NIM, Supabase, webhook) trafega para o frontend.
