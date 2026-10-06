"""Mapeamento AudioSet (PANNs) → IDs do catálogo (FASE 3F).

Regras de honestidade (testadas):
- SOMENTE rótulos que o modelo realmente emite (verificado em runtime
  contra `panns_inference.labels`).
- Rótulos genéricos/técnicos sem correspondente viram `unmapped_class`
  em evidência, nunca instrumento falso.
- Sem tipos vocais (soprano/tenor/...): só presença (lead-vocal) e coro.
- Sem subtipos de percussão inventados: só classes verificadas.
- "Guitar"/"Marimba, xylophone"/"Saxophone" são ambíguos por natureza
  e geram grupo `ambiguous`, não afirmação única.
"""

# Rótulo exato do AudioSet -> id(s) do catálogo (lista = ambíguo).
LABEL_MAP = {
    "Piano": ["piano"],
    "Electric piano": ["electric-piano"],
    "Organ": ["organ"],
    "Hammond organ": ["hammond-organ"],
    "Harpsichord": ["harpsichord"],
    "Synthesizer": ["synthesizer"],
    "Guitar": ["acoustic-guitar", "electric-guitar"],
    "Bass guitar": ["electric-bass"],
    "Double bass": ["double-bass"],
    "Violin, fiddle": ["violin"],
    "Cello": ["cello"],
    "Drum kit": ["drum-kit"],
    "Drum": ["drum-kit"],
    "Snare drum": ["snare"],
    "Hi-hat": ["hihat"],
    "Cymbal": ["crash"],
    "Timpani": ["timpani"],
    "Tambourine": ["tambourine"],
    "Maraca": ["maracas"],
    "Flute": ["flute"],
    "Saxophone": ["alto-sax", "tenor-sax"],
    "Clarinet": ["clarinet"],
    "Harp": ["harp"],
    "Accordion": ["accordion"],
    "Harmonica": ["harmonica"],
    "Bagpipes": ["bagpipes"],
    "Trombone": ["trombone"],
    "Trumpet": ["trumpet"],
    "French horn": ["french-horn"],
    "Marimba, xylophone": ["marimba", "xylophone"],
    "Vibraphone": ["vibraphone"],
    "Sitar": ["sitar"],
    "Ukulele": ["ukulele"],
    "Banjo": ["banjo"],
    "Mandolin": ["mandolin"],
    "Singing": ["lead-vocal"],
    "Chant": ["lead-vocal"],
    "Hum": ["lead-vocal"],
    "Humming": ["lead-vocal"],
    "Yodeling": ["lead-vocal"],
    "Rapping": ["lead-vocal"],
    "Choir": ["choir-mixed"],
}

# IDs de voz por tipo (NUNCA alvos do PANNs): guarda anti-afirmação.
VOICE_TYPE_IDS = {
    "soprano", "mezzo-soprano", "contralto", "tenor-voice",
    "baritone-voice", "bass-voice", "female-voice", "male-voice",
    "child-voice",
}


def supported_ids():
    """IDs alcançáveis pelo mapeamento (para model_supported)."""
    out = set()
    for targets in LABEL_MAP.values():
        out.update(targets)
    return out
