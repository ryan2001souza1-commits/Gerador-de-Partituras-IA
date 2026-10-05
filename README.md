# Gerador de Partituras IA

Descreva uma música em linguagem natural e receba uma partitura estruturada:
visualização, reprodução de áudio no navegador e exportação para PDF e MIDI.

## Arquitetura

```
Frontend (HTML/CSS/JS puro, Web Audio API)
  → PHP API (validação, sessão, ownership)
  → Python (regras locais OU provedor de IA)
  → score_model.py (validação canônica — ponto único de confiança)
  → Neon PostgreSQL → frontend
```

A IA produz **somente JSON musical**. Ela não acessa banco, autenticação,
PDF ou MIDI. Toda resposta da IA é normalizada e validada antes de
qualquer uso; inválida → erro controlado, nada é salvo.

## Variáveis de ambiente necessárias

| Variável | Onde | Obrigatória | Descrição |
|---|---|---|---|
| `DATABASE_URL` | local (`.env.local`, ignorado pelo Git) e Vercel | sim (banco) | Conexão PostgreSQL/Neon |
| `AI_API_KEY` | **somente servidor/Vercel** — nunca frontend/Git | não | Chave do provedor de IA. Ausente = geração local |
| `AI_BASE_URL` | servidor/Vercel | não | Padrão `https://api.openai.com/v1` (qualquer endpoint compatível) |
| `AI_MODEL` | servidor/Vercel | não | Padrão econômico atual `gpt-4.1-mini` (OpenAI Responses API) |
| `AI_TIMEOUT_S` | servidor/Vercel | não | Timeout HTTP em segundos (padrão 25, máx. 120) |

Nenhuma chave real deve aparecer em código, README, logs ou Git.

## IA (OpenAI Responses API)

- Requisição: `POST {AI_BASE_URL}/responses` com `model` (de `AI_MODEL`),
  `instructions`, `input` e `max_output_tokens` — somente `urllib`, sem SDK.
- Resposta: envelope `output[]` com partes `output_text`; recusa, status
  não-concluído ou texto ausente são rejeitados.
- A IA retorna **só JSON** (`title` + `notes`); parâmetros musicais valem do
  pedido do usuário. Tudo passa por `score_model.validate_score`.
- Falha da IA → erro exato sem fallback silencioso; sem chave → geração
  local identificada (`generator.type: "local"`).
- Chave **somente** no servidor/Vercel (Environment Variables). Sem chave
  real em código, README, logs ou Git.

## Como configurar a IA

1. Obtenha uma chave de um provedor compatível com Chat Completions.
2. Local: `export AI_API_KEY="..."` antes de subir o `php -S`.
3. Vercel: Project → Settings → Environment Variables (`AI_API_KEY`,
   opcionalmente `AI_BASE_URL`, `AI_MODEL`, `AI_TIMEOUT_S`).
4. Sem a chave, o projeto gera localmente (regras determinísticas) e
   informa isso na resposta (`generator.type: "local"`).

## Fluxo da geração

1. Frontend envia os 7 parâmetros (sem `user_id`) para `POST /api/generate.php`.
2. Sem `AI_API_KEY`: regras locais em PHP (`ScoreFactory::buildLocal`).
   Com chave: `AiClient` chama `POST {AI_BASE_URL}/responses` (OpenAI
   Responses API ou gateway compatível como OpenRouter) e `ScoreFactory`
   normaliza/valida. Falha da IA → erro exato, sem fallback silencioso.
   (Os scripts `python/` seguem disponíveis para desenvolvimento local.)
3. Python: com chave → prompt + chamada HTTPS → extrai JSON → normaliza
   (parâmetros musicais autoritativos do pedido) → valida; sem chave →
   regras locais. Falha da IA → erro amigável exato, sem fallback silencioso.
4. PHP persiste (só autenticados, `user_id` da sessão) e responde.
5. Frontend exibe, toca (Web Audio), exporta PDF/MIDI do mesmo `score_data`.

## Validação e segurança

- `score_model.validate_score`: notas, oitavas 0–8, durações, BPM 20–300,
  compassos, tons, instrumentos, dificuldades, máx. 300 notas (IA: 120).
- Limites: descrição ≤ 2000 chars, corpo JSON ≤ 64 KiB, resposta IA ≤ 128 KiB.
- PDO + prepared statements; senhas com `password_hash`; sessão com
  `HttpOnly`/`SameSite=Lax`/regenerate/timeout; erros genéricos ao cliente.
- Provedor trocável: basta implementar `AIProvider.generate_music`
  (ver `python/ai_provider.py`).

## Desenvolvimento local

```bash
php -S localhost:8000            # com DATABASE_URL e (opcional) AI_API_KEY no ambiente
python3 -m py_compile python/*.py
node --check js/app.js
```

## Deploy na Vercel

- Runtime PHP precisa de `pdo_pgsql`; Python roda como função/serverless.
- `DATABASE_URL` e `AI_API_KEY` via Environment Variables (nunca em arquivo).
- Geração é em memória; sessões PHP em arquivo não persistem entre
  invocações serverless (para produção, migrar sessão para o banco/token).
