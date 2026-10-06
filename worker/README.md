# Worker de áudio (FASE 3A — fundação)

Esqueleto FastAPI do futuro worker de DSP. Nesta fase: só saúde e
endpoint interno de teste. Sem Supabase, sem áudio, sem webhook.

## Setup

```bash
cd worker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Iniciar

```bash
uvicorn app:app --host 127.0.0.1 --port 8001
```

## Testar

```bash
# saúde
curl http://127.0.0.1:8001/health
# → {"ok":true,"service":"audio-worker"}

# teste interno
curl -X POST http://127.0.0.1:8001/jobs/test \
  -H 'Content-Type: application/json' \
  -d '{"job_id":"abc-123"}'
# → {"accepted":true,"job_id":"abc-123","status":"queued"}
```

## Testes automatizados

```bash
python -m unittest discover -s tests
```

## Ingestão (FASE 3B)

`POST /jobs/ingest` com `{"job_id": "...", "source_url": "https://..."}`:
baixa por streaming para diretório temporário, valida com `ffprobe` e
responde `validated` (sempre limpa o temporário; nada persiste).

## Normalização (FASE 3C)

`POST /audio/normalize` (teste local): converte para WAV PCM s16le,
44100 Hz, estéreo, validando a saída. Sem loudness/ganho/dinâmica —
só formato. O original nunca é alterado.

## Análise de stems (FASE 3E)

`POST /audio/analyze-stems` com `{"stems": {"bass": "/tmp/.../bass.wav"},
"metadata": {...}}`: evidências espectrais reais (NumPy) + hipóteses
por stem, sem rede e sem Supabase.

```
Áudio
↓
FFmpeg (decode)
↓
Normalização (WAV 44100/estéreo)
↓
Demucs
↓
vocals / drums / bass / other
↓
Instrument Analysis (evidência + hipótese calibrada)
↓
InstrumentDetection[]
```

**Explícito: Demucs realiza separação de fontes. A identificação de
instrumentos é uma etapa independente** — sem classificador neural, o
stem `other` nunca gera nome de instrumento (só evidência + aviso), e
hipóteses heurísticas ficam abaixo de 0.80 com `direct_detection`
falso e evidências registradas.

Por que existe: todo DSP posterior (BPM, stems, pitch) precisa de um
formato único e previsível. Formato padrão: WAV PCM s16le, 44100 Hz,
estéreo, sem alterar volume.

`POST /audio/normalize` (teste local): converte para WAV PCM s16le,
44100 Hz, estéreo, validando a saída. Sem loudness/ganho/dinâmica —
só formato. O original nunca é alterado.

## Dependências externas

- `ffmpeg`/`ffprobe` (validação de áudio). Verifique com:

```bash
ffmpeg -version
ffprobe -version
```

Sem eles, `/jobs/ingest` responde erro claro de dependência ausente
(nada é instalado automaticamente).

## Limites atuais

- `AUDIO_MAX_BYTES` (padrão 25 MB), `AUDIO_DOWNLOAD_TIMEOUT_S`
  (padrão 30s), `AUDIO_TMP_DIR` (padrão do sistema).
- Só `http/https`; localhost e IPs privados são recusados (anti-SSRF);
  sem seguir redirects.

## Notas

- Secrets (`SUPABASE_SERVICE_ROLE_KEY`, `CALLBACK_TOKEN`) nunca são
  obrigatórios nesta fase e jamais são impressos.
- DSP real (FFmpeg/Demucs/Essentia/Basic Pitch/CREPE) entra nas
  próximas fases, sem mudar estes endpoints.

## Classificador real (FASE 3F)

```
Áudio
↓
FFmpeg (decode)
↓
Normalização (WAV 44100/estéreo)
↓
Demucs (htdemucs, CPU)
↓
vocals / drums / bass / other
↓
Evidência espectral (NumPy)
↓
PANNs CNN14 (CPU) → probabilidades → agregação → mapeamento
↓
InstrumentDetection[]
```

- `POST /audio/analyze-stems` usa o classificador real por padrão
  (`classifier="panns"`); com modelo ausente, faz fallback só-heurístico
  com aviso explícito (sem inventar instrumento; `other` sem modelo
  nunca gera nome).
- Adapter: `audio/panns_classifier.py` (`PannsClassifier` com
  `load()`/`is_available()`/`classify()`/`classify_stem()`), registrado
  em `audio/classifiers.py`. Troca de modelo não exige mudar análise,
  catálogo, endpoint ou persistência.
- Pré-processamento: WAV → mono → 32 kHz (resample via torchaudio) →
  janelas de 10 s (todas analisadas; última com zero-pad) → CNN14 →
  agregação temporal (média, máximo, janelas ativas).
- Agregação (`audio/panns_classifier.py`, sem valores escondidos):
  `MIN_CONFIDENCE=0.35`, `MIN_ACTIVE_WINDOWS=2`,
  `MIN_ACTIVE_RATIO=0.30`, `AMBIGUITY_MARGIN=0.08`.
- Mapeamento (`audio/panns_mapping.py`): somente rótulos reais do
  AudioSet verificados em runtime contra `panns_inference.labels`;
  sem correspondência vira `unmapped_class` em evidência (nunca
  instrumento falso). `Guitar`/`Marimba, xylophone`/`Saxophone` geram
  grupo `ambiguous`, não afirmação única. Voz: só `lead-vocal` e
  `choir-mixed` (sem soprano/tenor/etc.). Percussão: só classes
  verificadas (`drum-kit`, `snare`, `hihat`, `crash`, `timpani`,
  `tambourine`, `maracas`); `kick`/`toms` não são afirmados.
- Catálogo: `model_supported` marca os IDs alcançáveis pelo PANNs
  (sincronia testada contra o mapeamento).

Modelo:

- MODEL_NAME: Cnn14_mAP=0.431 (PANNs)
- MODEL_VERSION: Cnn14_mAP=0.431
- FRAMEWORK: PyTorch (panns-inference 0.1.1, torch CPU)
- LICENSE: código panns-inference MIT; pesos oficiais de
  https://zenodo.org/record/3987831/files/Cnn14_mAP%3D0.431.pth?download=1
  (uso com atribuição; COMPATÍVEL: sim — sem copyleft; MOTIVO: MIT +
  pesos de pesquisa de fonte oficial, sem redistribuição no Git).
- INPUT_FORMAT: WAV PCM (8/16/32-bit) lido via `wave`
- SAMPLE_RATE: 32000 Hz (resample interno)
- MONO/STEREO: mono (média dos canais)
- CLASSES: 527 rótulos AudioSet; ~30 mapeados p/ instrumentos
  (piano, electric-piano, organ, hammond-organ, harpsichord,
  synthesizer, acoustic-guitar, electric-guitar, electric-bass,
  double-bass, violin, cello, drum-kit, snare, hihat, crash, timpani,
  tambourine, maracas, flute, alto-sax, tenor-sax, clarinet, harp,
  accordion, harmonica, bagpipes, trombone, trumpet, french-horn,
  marimba, xylophone, vibraphone, sitar, ukulele, banjo, mandolin,
  lead-vocal, choir-mixed).
- MODEL_SIZE: 327428481 bytes (sha256 prefixo `0dc499e40e9761ef`)
- CPU_REQUIREMENT: CPU apenas (esteira `device="cpu"`; CUDA nunca tentado)
- Cache: `~/.cache/gpi-models/panns/Cnn14_mAP0.431.pth` (fora do Git;
  `.gitignore` cobre `*.pth/*.wav/*.mp3`).

Limitações (a classificação não é perfeita):

- Tons sintéticos/silêncio não geram detecção neural (correto);
  heurísticas ficam <0.80 com `direct_detection: false`.
- `violão vs guitarra`, `piano vs teclado`, `violino vs viola` podem
  sair como `ambiguous` com candidatos + probabilidades.
- Demucs separa fontes, não identifica instrumentos.

Performance em CPU (medida, tons sintéticos + stems silenciosos):

- MODEL_LOAD: ~6.5 s (CPU, ~1 GB RSS)
- INFERENCE: ~1.7–2.1 s por stem de 2–8 s (1 janela de 10 s)
- WINDOWS: 1 por stem curto; N por stems longos (12 s → 2 janelas)
- CPU: cpu (CUDA indisponível; nunca tentado)

## Transcrição musical (FASE 3G)

```
Áudio
↓
FFmpeg (decode)
↓
Normalização (WAV 44100/estéreo)
↓
Demucs (htdemucs, CPU)
↓
vocals / drums / bass / other
↓
PANNs CNN14 → instrument detection (etapa independente)
↓
Basic Pitch (TFLite, CPU) → notas → MIDI
```

**"Instrument detection e music transcription são etapas
independentes."** A transcrição não depende do PANNs; aceita
`instrument_id` opcional (futuro: canal/programa MIDI, clave,
tessitura) sem implementar renderização de partitura.

- `POST /audio/transcribe` local com `{"audio_path": "/tmp/...wav",
  "stem": "other"|"bass"|"vocals"|"drums", "instrument_id": "..."}`:
  mesmas guardas do `/audio/analyze-stems` (diretório permitido, sem
  URLs, sem traversal/symlink/SSRF). Sem Supabase, sem webhook.
- Adapter: `audio/transcriber.py` (`MusicTranscriber` com
  `is_available()`/`load()`/`transcribe()`/`transcribe_stem()`).
- Pré-processamento: WAV → Basic Pitch reamostra p/ 22050 Hz e
  down-mixa p/ mono internamente; qualquer sample rate de entrada é
  aceito (16 k/44.1 k testados).
- Saída normalizada (independente da lib): `TranscribedNote`
  (`pitch`, `start`, `end`, `duration`, `velocity`, `confidence`) e
  `TranscriptionResult` (`sample_rate`, `duration_seconds`, `notes`,
  `midi_path`, `model`, `model_version`, `warnings`, `metadata`).
  `confidence` = amplitude do modelo (0–1); `None` quando ausente —
  nunca inventada. `bpm` sempre `"unknown"` (modelo não fornece).
- MIDI real via `midi_data.write()` do modelo (cabeçalho `MThd`
  validado, tracks/PPQ/duração verificáveis com pretty_midi).
  Nada de arquivo vazio: silêncio gera MIDI válido com 0 notas +
  aviso "nenhuma nota detectada".
- Política por stem: `vocals`/`bass` = melódica, `other` = polifônica,
  `drums` = sem notas melódicas (retorna vazio + aviso, `midi_path`
  `None` — sem MIDI falso).
- Deduplicação só de duplicatas comprovadas (mesmo
  pitch+início+fim); acordes simultâneos preservados.
- Range MIDI 0–127 validado (fora = rejeitado, não corrigido).
- Timing original preservado; `quantize_notes()` existe como etapa
  opcional, nunca automática.

Modelo:

- MODEL_NAME: basic-pitch-icassp2022
- MODEL_VERSION: 0.4.0-icassp2022-tflite
- FRAMEWORK: tflite-runtime 2.14.0 (CPU)
- LICENSE: Apache-2.0 (Spotify basic-pitch; COMPATÍVEL: sim —
  permissiva, sem copyleft)
- INPUT_FORMAT: WAV PCM (qualquer SR; reamostragem interna p/ 22050)
- MONO/STEREO: mono (down-mix interno)
- MODEL_SIZE: 204448 bytes (TFLite embutido no pacote, fora do Git)
- CPU_REQUIREMENT: CPU apenas (CUDA nunca tentado)
- Dependência crítica: `numpy==1.26.4` (tflite-runtime 2.14.0 é
  incompatível com NumPy 2 — `_ARRAY_API not found`).

Limitações (transcrição não é perfeita):

- Harmônicos podem gerar nota espúria de baixa confiança (ex. D6
  vel 42/conf 0.33 num acorde C-E-G).
- Monofonia precisa; polifonia densa pode fundir/omitir notas.
- Sem BPM, sem quantização automática, sem programa/canal por
  instrumento ainda.

Performance em CPU (peça musical 4.0 s, 10 eventos):

- MODEL_LOAD: ~1.4 s (quente) / ~11 s (frio, 1ª carga)
- INFERENCE: ~2.2 s → REAL_TIME_FACTOR ~0.55x
- CPU: cpu (CUDA indisponível; nunca tentado)

## Hospedagem externa (FASE WORKER PÚBLICO)

O worker é um serviço HTTP FastAPI autocontido (sem Supabase, sem
Vercel). O processamento pesado roda em background: `POST
/jobs/transcribe` valida e responde `{"accepted":true,...}` em
milissegundos; o pipeline (Demucs → PANNs → Basic Pitch → webhook)
continua fora da conexão inicial.

### Variáveis de ambiente

| Variável | Obrigatória | Padrão | Uso |
|---|---|---|---|
| `WORKER_WEBHOOK_SECRET` | sim (p/ callback) | `""` | header `X-Webhook-Secret` no webhook; nunca vai no JSON nem nos logs |
| `WORKER_HOST` / `WORKER_PORT` | não | `127.0.0.1` / `8001` | bind local (Docker usa `0.0.0.0`) |
| `AUDIO_TMP_DIR` | não | sist. (`/tmp/gpi` no Docker) | temporários (sempre limpos, mesmo em falha) |
| `AUDIO_MAX_BYTES` | não | `26214400` | teto do download |
| `DEMUCS_MODEL` / `DEMUCS_DEVICE` / `DEMUCS_TIMEOUT_S` | não | `htdemucs` / `auto` / `600` | `auto` usa CUDA quando há GPU, senão CPU |

### Local

```bash
cd worker
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
WORKER_WEBHOOK_SECRET=... uvicorn app:app --host 127.0.0.1 --port 8001
```

### Docker CPU

```bash
docker build -t gpi-worker:cpu ./worker
docker run --rm -p 8001:8001 \
  -e WORKER_WEBHOOK_SECRET=... \
  -v gpi-models:/home/appuser/.cache \
  gpi-worker:cpu
```

### Docker GPU

```bash
docker build -t gpi-worker:gpu ./worker \
  --build-arg BASE_IMAGE=nvidia/cuda:12.1.1-runtime-ubuntu22.04 \
  --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu121 \
  --build-arg TORCH_VERSION=2.14.1+cu121
docker run --rm --gpus all -p 8001:8001 \
  -e WORKER_WEBHOOK_SECRET=... \
  -v gpi-models:/home/appuser/.cache \
  gpi-worker:gpu
```

Sem GPU, tudo roda em CPU (fallback automático). Modelos: PANNs
baixado no build com checagem de tamanho; Demucs baixa no primeiro
uso (ou no warmup com `PRELOAD_MODELS=true`); Basic Pitch já vem no
pacote pip. Nenhum secret entra na imagem (usuário `appuser`,
healthcheck em `GET /health`).
