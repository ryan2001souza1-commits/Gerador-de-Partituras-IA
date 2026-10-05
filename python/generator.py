#!/usr/bin/env python3
"""Gerador de Partituras IA — orquestrador (regras locais + IA real).

Lê JSON pela entrada padrão (stdin) e devolve JSON pela saída padrão
(stdout). Fluxo:

    1. valida os parâmetros (score_model.validate_params);
    2. se AI_API_KEY existir: chama o provedor (ai_provider), extrai o
       JSON, normaliza para o formato canônico e valida tudo com
       score_model.validate_score;
    3. sem chave: geração local determinística (status
       "generated-rule-based", claramente identificada);
    4. IA indisponível/inválida: erro controlado, NADA é salvo e NÃO há
       substituição silenciosa pela geração local.

A IA produz SOMENTE estrutura musical. Banco, auth, PDF e MIDI estão
fora do alcance dela. Sem eval/exec. Somente biblioteca padrão.

Protocolo:
    stdin  -> {"descricao": str, "instrumento": str, "tom": str, ...}
    stdout -> {"success": true, "message": str, "score": {...}, "meta": {...}}
               ou {"success": false, "error": str}
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai_provider import (  # noqa: E402
    AI_UNAVAILABLE_MESSAGE,
    AIConfigError,
    AIProviderError,
    extract_json,
    get_provider,
)
from score_model import (  # noqa: E402
    AI_MAX_NOTES,
    ANDAMENTO_TO_BPM,
    DIFICULDADE_TO_LEVEL,
    DURATIONS,
    ESTILO_TO_STYLE,
    INSTRUMENT_OCTAVES,
    PITCHES,
    ScoreValidationError,
    TOM_TO_KEY,
    build_deterministic_score,
    validate_params,
    validate_score,
)

AI_NOTES_REQUESTED = 20
DURATION_ALIASES = {
    "semibreve": "whole",
    "minima": "half", "minim": "half",
    "seminima": "quarter", "crotchet": "quarter",
    "colcheia": "eighth", "quaver": "eighth",
    "semicolcheia": "sixteenth", "semiquaver": "sixteenth",
}
DIFFICULTY_ALIASES = {"easy": "beginner", "medium": "intermediate", "hard": "advanced"}


def read_input():
    """Lê e decodifica o JSON recebido via stdin."""
    raw = sys.stdin.read()
    if not raw or not raw.strip():
        raise ValueError("Entrada vazia.")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("JSON inválido.")
    if not isinstance(data, dict):
        raise ValueError("Dados inválidos.")
    return data


def build_prompt(data):
    """Prompt interno: parâmetros + descrição, resposta SOMENTE JSON."""
    from score_model import beats_per_measure, scale_pitches, tonic_of
    lo, hi = INSTRUMENT_OCTAVES.get(data["instrumento"], (4, 5))
    key = TOM_TO_KEY[data["tom"]]
    scale = " ".join(scale_pitches(key))
    beats = beats_per_measure(data["compasso"])
    beats_label = str(int(beats)) if beats == int(beats) else str(beats)
    tonic = tonic_of(key)
    return (
        "Componha uma melodia com {n} notas para {instrumento} em {tom}, "
        "{bpm} BPM, compasso {compasso}, nível {dificuldade}, estilo {estilo}, "
        'sobre: "{descricao}".\n'
        "Responda SOMENTE com JSON válido, sem texto antes ou depois, "
        "neste formato exato:\n"
        '{{"title": "...", "notes": ['
        '{{"pitch": "C4", "duration": "quarter", "rest": false}}, ...]}}\n'
        "Regras: pitch é nota A-G com # opcional + oitava (ex. C4, F#5); "
        "oitavas entre {lo} e {hi}; duration é um de "
        "whole|half|quarter|eighth|sixteenth; pausas usam "
        '{{"pitch": null, "duration": "...", "rest": true}}; '
        "exatamente {n} notas.\n"
        "Regras musicais (obrigatórias): use APENAS estas alturas da "
        "escala de {tom}: {scale}; cada compasso de {compasso} soma "
        "exatamente {beats} tempos — complete todos os compassos; "
        "prefira graus conjuntos com salto máximo de 7 semitons e nunca "
        "salte de oitava sem retorno por graus conjuntos; repita um "
        "motivo de 1 compasso com variação e termine na tônica ({tonic}) "
        "com nota longa."
    ).format(
        n=AI_NOTES_REQUESTED,
        instrumento=data["instrumento"],
        tom=data["tom"],
        bpm=ANDAMENTO_TO_BPM[data["andamento"]],
        compasso=data["compasso"],
        dificuldade=data["dificuldade"],
        estilo=data["estilo"],
        descricao=data["descricao"].strip()[:2000],
        lo=lo,
        hi=hi,
        scale=scale,
        beats=beats_label,
        tonic=tonic,
    )


def normalize_ai_note(raw, order):
    """Converte uma nota da IA para o formato canônico (ou rejeita)."""
    if not isinstance(raw, dict):
        raise ScoreValidationError("Nota inválida na resposta da IA.")
    rest = raw.get("rest", False)
    if not isinstance(rest, bool):
        raise ScoreValidationError("Nota inválida na resposta da IA.")
    pitch, octave = None, 4
    if not rest:
        token = raw.get("pitch")
        if isinstance(token, dict):  # tolera {pitch, octave} separados
            token, octave = token.get("pitch"), token.get("octave", 4)
        if not isinstance(token, str):
            raise ScoreValidationError("Nota inválida na resposta da IA.")
        token = token.strip()
        if len(token) >= 2 and token[-1].isdigit():
            pitch, octave = token[:-1], int(token[-1])
        else:
            pitch = token
            maybe_oct = raw.get("octave")
            if isinstance(maybe_oct, int):
                octave = maybe_oct
        if pitch not in PITCHES:
            raise ScoreValidationError("Nota inválida na resposta da IA.")
        if not isinstance(octave, int) or not 0 <= octave <= 8:
            raise ScoreValidationError("Nota inválida na resposta da IA.")
    dur = raw.get("duration")
    if not isinstance(dur, str):
        raise ScoreValidationError("Nota inválida na resposta da IA.")
    dur = DURATION_ALIASES.get(dur.strip().lower(), dur.strip().lower())
    if dur not in DURATIONS:
        raise ScoreValidationError("Nota inválida na resposta da IA.")
    return {"pitch": pitch, "octave": octave, "duration": dur,
            "order": order, "rest": rest}


def normalize_ai_score(raw, data, provider_info):
    """Monta a partitura canônica a partir da resposta da IA.

    Parâmetros musicais (tom, BPM, compasso, dificuldade, estilo,
    instrumento) são AUTORITATIVOS do pedido validado — a IA compõe
    título e notas dentro deles. Garante compatibilidade com Neon,
    PDF, MIDI e player.
    """
    if not isinstance(raw, dict):
        raise ScoreValidationError("Resposta inválida da IA.")
    notes_raw = raw.get("notes")
    if not isinstance(notes_raw, list) or not notes_raw:
        raise ScoreValidationError("Resposta inválida da IA.")
    if len(notes_raw) > AI_MAX_NOTES:
        raise ScoreValidationError("Resposta inválida da IA.")
    notes = [normalize_ai_note(n, i) for i, n in enumerate(notes_raw)]

    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        title = "{} para {} em {}".format(
            data["estilo"], data["instrumento"], data["tom"])
    title = title.strip()[:200]

    score = {
        "title": title,
        "instrument": data["instrumento"],
        "musical_key": TOM_TO_KEY[data["tom"]],
        "tempo": ANDAMENTO_TO_BPM[data["andamento"]],
        "time_signature": data["compasso"],
        "difficulty": DIFICULDADE_TO_LEVEL[data["dificuldade"]],
        "style": ESTILO_TO_STYLE[data["estilo"]],
        "notes": notes,
        "labels": {
            "instrumento": data["instrumento"],
            "tom": data["tom"],
            "andamento": data["andamento"],
            "compasso": data["compasso"],
            "dificuldade": data["dificuldade"],
            "estilo": data["estilo"],
        },
        "generator": {"type": "ai", "provider": provider_info["provider"],
                      "model": provider_info["model"]},
        "status": "generated-ai",
    }
    validate_score(score)
    return score


def generate_score(data):
    """Gera via IA quando configurada; senão, regras locais.

    Retorna (score, meta). Levanta ValueError/ScoreValidationError para
    entradas inválidas e AIProviderError para falhas da IA.
    """
    validate_params(data)
    try:
        provider = get_provider()
    except AIConfigError:  # sem chave => geração local determinística
        score = build_deterministic_score(data)
        score["generator"] = {"type": "local", "provider": "rule-based",
                              "model": "score-model-v1"}
        meta = {"generator": "local", "provider": "rule-based",
                "model": "score-model-v1"}
        return score, meta, "Partitura gerada localmente (IA não configurada)."

    try:
        prompt = build_prompt(data)
        resp = provider.generate_music(prompt, {
            "instrumento": data["instrumento"], "tom": data["tom"],
            "bpm": ANDAMENTO_TO_BPM[data["andamento"]],
            "compasso": data["compasso"], "dificuldade": data["dificuldade"],
            "estilo": data["estilo"], "notas": AI_NOTES_REQUESTED,
        })
        raw = extract_json(resp["text"])
        score = normalize_ai_score(raw, data, resp)
        meta = {"generator": "ai", "provider": resp["provider"],
                "model": resp["model"]}
        return score, meta, "Partitura gerada com IA."
    except (AIProviderError, ScoreValidationError) as exc:
        raise AIProviderError(AI_UNAVAILABLE_MESSAGE) from exc


# Mantida a assinatura histórica para a futura IA externa direta.
def generate_with_ai(data, provider=None):
    """Variante injetável (testes): usa o provider informado."""
    validate_params(data)
    if provider is None:
        provider = get_provider()
    resp = provider.generate_music(build_prompt(data), {})
    raw = extract_json(resp["text"])
    return normalize_ai_score(raw, data, resp)


def main():
    try:
        data = read_input()
        score, meta, message = generate_score(data)
        response = {"success": True, "message": message,
                    "score": score, "meta": meta}
        sys.stdout.write(json.dumps(response, ensure_ascii=False))
    except AIProviderError:
        # IA falhou: erro amigável exato; nada foi salvo.
        sys.stdout.write(json.dumps(
            {"success": False, "error": AI_UNAVAILABLE_MESSAGE},
            ensure_ascii=False))
        sys.exit(2)
    except ValueError as exc:
        # Entrada inválida: mensagem específica (contrato existente).
        sys.stdout.write(json.dumps({"success": False, "error": str(exc)},
                                    ensure_ascii=False))
        sys.exit(2)
    except Exception:  # noqa: BLE001 - nunca expor rastros internos
        sys.stdout.write(json.dumps(
            {"success": False, "error": "Erro interno ao processar a solicitação."},
            ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
