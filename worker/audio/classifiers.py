"""Adaptadores de classificação (FASE 3E/3F).

Contrato do adapter neural: `load()`, `is_available()`,
`classify(audio_path)`, `classify_stem(audio_path, stem_name)`.
Sem modelo neural disponível, o adaptador padrão declara
indisponibilidade explícita — nenhuma confiança é inventada.
Modelos futuros entram pelo registro, com cache único em memória.
"""

_classifier_cache = {}


class UnavailableClassifier:
    """Adaptador sem modelo: sempre vazio, com motivo explícito."""

    name = "unavailable"
    version = "none"
    reason = (
        "classificador neural indisponível neste ambiente "
        "(sem Essentia/TensorFlow nem modelo ONNX carregado)"
    )

    def is_available(self):
        return False

    def load(self):
        raise RuntimeError(self.reason)

    def classify(self, stem_path, evidence=None):
        return []

    def classify_stem(self, stem_path, stem_name, evidence=None):
        return []


def get_classifier(name="default"):
    """Devolve o classificador registrado (com cache único)."""
    if name in _classifier_cache:
        return _classifier_cache[name]
    if name in ("default", "unavailable"):
        clf = UnavailableClassifier()
    elif name in ("panns", "panns-cnn14"):
        from audio.panns_classifier import PannsClassifier
        clf = PannsClassifier()
    else:
        raise ValueError("Classificador desconhecido: " + str(name))
    _classifier_cache[name] = clf
    return clf


def model_versions(active="unavailable"):
    """Versões dos modelos em uso (para o relatório). Nunca lança."""
    versions = {"engine": "spectral-v1"}
    if active in ("unavailable", "default"):
        versions["classifier"] = "unavailable"
        return versions
    try:
        clf = get_classifier(active)
        versions["classifier"] = getattr(clf, "version", active)
    except Exception:
        versions["classifier"] = "unavailable"
    return versions
