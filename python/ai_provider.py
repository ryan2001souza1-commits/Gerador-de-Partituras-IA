"""Gerador de Partituras IA — camada de provedor de IA.

A IA produz SOMENTE estrutura musical JSON. Ela nunca acessa banco,
autenticação, PDF ou MIDI: a resposta sempre passa por
score_model.validate_score antes de qualquer uso.

Arquitetura trocável: todo o projeto depende apenas da interface
``AIProvider.generate_music``. O padrão é a OpenAI Responses API
(``POST {base}/responses``), usando SOMENTE urllib da stdlib —
sem SDKs, ideal para serverless. Outro provedor futuro: implementar
a mesma interface, sem tocar no restante do projeto.

Variáveis de ambiente (servidor/Vercel — nunca no frontend/Git):
    AI_API_KEY   segredo do provedor (ausente => IA desabilitada)
    AI_BASE_URL  ex. https://api.openai.com/v1 (opcional)
    AI_MODEL     modelo OpenAI (opcional; padrão econômico atual)
    AI_TIMEOUT_S segundos de timeout HTTP (opcional, padrão 25)

Segurança: timeout sempre configurado, prompt limitado (descrição já
limitada a 2000 chars), resposta limitada a 128 KiB, sem eval/exec, sem
logs de segredos, mensagens de erro controladas e genéricas.
"""

import json
import os
import urllib.error
import urllib.request

AI_RESPONSE_MAX_BYTES = 131072
DEFAULT_BASE_URL = "https://api.openai.com/v1"
# Padrão econômico atual para esta tarefa; trocável via AI_MODEL sem código.
DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_TIMEOUT_S = 25

AI_UNAVAILABLE_MESSAGE = "Não foi possível gerar a partitura com IA. Tente novamente."
AI_NOT_CONFIGURED_MESSAGE = "Serviço de IA não configurado."


class AIProviderError(Exception):
    """Erro controlado do provedor (mensagem segura para o usuário)."""


class AIConfigError(AIProviderError):
    """Configuração ausente (sem chave)."""


class AITimeoutError(AIProviderError):
    """Estouro de timeout na chamada."""


class AIProvider:
    """Interface: todo provedor implementa generate_music."""

    name = "base"

    def generate_music(self, prompt, parameters):
        """Retorna dict decodificado da resposta. Levanta AIProviderError."""
        raise NotImplementedError


class OpenAIResponsesProvider(AIProvider):
    """Cliente da OpenAI Responses API (POST /responses)."""

    name = "openai-responses"

    def __init__(self, api_key, base_url=None, model=None, timeout_s=None):
        if not api_key or not isinstance(api_key, str):
            raise AIConfigError(AI_NOT_CONFIGURED_MESSAGE)
        self.api_key = api_key
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or DEFAULT_MODEL
        try:
            self.timeout_s = int(timeout_s) if timeout_s else DEFAULT_TIMEOUT_S
        except (TypeError, ValueError):
            self.timeout_s = DEFAULT_TIMEOUT_S
        if self.timeout_s <= 0 or self.timeout_s > 120:
            self.timeout_s = DEFAULT_TIMEOUT_S

    def generate_music(self, prompt, parameters):
        payload = {
            "model": self.model,
            "instructions": (
                "Você é um compositor que responde SOMENTE com JSON válido, "
                "sem texto antes ou depois, sem markdown."),
            "input": prompt,
            "temperature": 0.7,
            "max_output_tokens": 4000,
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/responses",
            data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = resp.read(AI_RESPONSE_MAX_BYTES + 1)
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            raise AIProviderError(AI_UNAVAILABLE_MESSAGE) from exc
        except (TimeoutError, OSError) as exc:  # inclui socket.timeout
            raise AITimeoutError(AI_UNAVAILABLE_MESSAGE) from exc
        if len(raw) > AI_RESPONSE_MAX_BYTES:
            raise AIProviderError(AI_UNAVAILABLE_MESSAGE)
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise AIProviderError(AI_UNAVAILABLE_MESSAGE) from exc
        text = self.extract_output_text(envelope)
        return {"text": text, "model": self.model, "provider": self.name}

    @staticmethod
    def extract_output_text(envelope):
        """Extrai o texto do envelope /responses, tolerando variações.

        Aceita itens message com partes output_text (e content textual
        direto). Recusa explícita, status não-concluído ou ausência de
        texto => AIProviderError.
        """
        if not isinstance(envelope, dict):
            raise AIProviderError(AI_UNAVAILABLE_MESSAGE)
        status = envelope.get("status")
        if status is not None and status != "completed":
            raise AIProviderError(AI_UNAVAILABLE_MESSAGE)
        output = envelope.get("output")
        if not isinstance(output, list) or not output:
            raise AIProviderError(AI_UNAVAILABLE_MESSAGE)
        texts = []
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "refusal":
                raise AIProviderError(AI_UNAVAILABLE_MESSAGE)
            content = item.get("content")
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "refusal":
                        raise AIProviderError(AI_UNAVAILABLE_MESSAGE)
                    text = part.get("text")
                    if part.get("type") == "output_text" and isinstance(text, str):
                        texts.append(text)
        joined = "\n".join(t for t in texts if t.strip()).strip()
        if not joined:
            raise AIProviderError(AI_UNAVAILABLE_MESSAGE)
        return joined


def get_provider():
    """Instancia o provedor a partir do ambiente. Sem chave => AIConfigError."""
    api_key = os.environ.get("AI_API_KEY", "")
    if not api_key.strip():
        raise AIConfigError(AI_NOT_CONFIGURED_MESSAGE)
    return OpenAIResponsesProvider(
        api_key=api_key.strip(),
        base_url=os.environ.get("AI_BASE_URL", ""),
        model=os.environ.get("AI_MODEL", ""),
        timeout_s=os.environ.get("AI_TIMEOUT_S", ""),
    )


def extract_json(text):
    """Extrai o JSON da resposta (tolera cercas markdown e texto ao redor).

    Retorna o objeto decodificado. Levanta AIProviderError se inválido.
    Nunca executa nada: apenas json.loads.
    """
    if not isinstance(text, str):
        raise AIProviderError(AI_UNAVAILABLE_MESSAGE)
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise AIProviderError(AI_UNAVAILABLE_MESSAGE)
    try:
        obj = json.loads(cleaned[start:end + 1])
    except ValueError as exc:
        raise AIProviderError(AI_UNAVAILABLE_MESSAGE) from exc
    if not isinstance(obj, dict):
        raise AIProviderError(AI_UNAVAILABLE_MESSAGE)
    return obj
