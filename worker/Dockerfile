# Gerador de Partituras IA — worker de áudio (FASE WORKER PÚBLICO).
#
# CPU (padrão):
#   docker build -t gpi-worker:cpu ./worker
#   docker run --rm -p 8001:8001 \
#     -e WORKER_WEBHOOK_SECRET=hunter2 \
#     -v gpi-models:/home/appuser/.cache \
#     gpi-worker:cpu
#
# GPU NVIDIA (requer NVIDIA Container Toolkit + `docker run --gpus all`):
#   docker build -t gpi-worker:gpu ./worker \
#     --build-arg BASE_IMAGE=nvidia/cuda:12.1.1-runtime-ubuntu22.04 \
#     --build-arg PYTHON_BIN=python3 \
#     --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu121 \
#     --build-arg TORCH_VERSION=2.5.1+cu121
#   (na base CUDA o apt instala o Python 3.10; o separador usa CUDA
#   sozinho quando torch.cuda.is_available(), senão cai para CPU.)
#
# Nenhum secret é copiado para a imagem. Modelos: PANNs é baixado no
# build com checagem de tamanho; Demucs baixa no primeiro uso (ou no
# warmup, ver PRELOAD_MODELS). Basic Pitch (tflite) vem no pacote pip.
# syntax=docker/dockerfile:1

ARG BASE_IMAGE=python:3.10-slim
FROM ${BASE_IMAGE} AS base

ARG PYTHON_BIN=python3
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG TORCH_VERSION=2.11.0+cpu
ARG PRELOAD_MODELS=true
ARG PANNS_URL=https://zenodo.org/record/3987831/files/Cnn14_mAP%3D0.431.pth?download=1
ARG PANNS_SIZE_BYTES=327428481

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/appuser \
    AUDIO_TMP_DIR=/tmp/gpi \
    PORT=8001

# FFmpeg (+python3-pip só quando a base CUDA não traz Python).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl ca-certificates python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && ffmpeg -version | head -1

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app /tmp/gpi /home/appuser/.cache \
    && chown -R appuser:appuser /app /tmp/gpi /home/appuser/.cache

WORKDIR /app
COPY --chown=appuser:appuser requirements-docker.txt app.py config.py models.py job_processor.py ./
COPY --chown=appuser:appuser audio/ ./audio/

USER appuser
RUN ${PYTHON_BIN} -m pip install --no-cache-dir --upgrade pip \
    && ${PYTHON_BIN} -m pip install --no-cache-dir \
        --extra-index-url ${TORCH_INDEX_URL} \
        "torch==${TORCH_VERSION}" "torchaudio==${TORCH_VERSION}" \
    && ${PYTHON_BIN} -m pip install --no-cache-dir -r requirements-docker.txt

# PANNs CNN14 (pesos oficiais; checagem de tamanho, sem segredo).
RUN if [ "${PRELOAD_MODELS}" = "true" ]; then \
      mkdir -p /home/appuser/.cache/gpi-models/panns && \
      curl -fsSL -o /home/appuser/.cache/gpi-models/panns/Cnn14_mAP0.431.pth "${PANNS_URL}" && \
      [ "$(stat -c%s /home/appuser/.cache/gpi-models/panns/Cnn14_mAP0.431.pth)" = "${PANNS_SIZE_BYTES}" ] && \
      ${PYTHON_BIN} -c "from demucs.pretrained import get_model; get_model('htdemucs'); print('demucs ok')"; \
    fi

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python3 -c "import sys,urllib.request,os; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8001'), timeout=4).status==200 else 1)"

CMD ["sh", "-c", "exec python3 -m uvicorn app:app --host 0.0.0.0 --port ${PORT:-8001} --workers 1"]
