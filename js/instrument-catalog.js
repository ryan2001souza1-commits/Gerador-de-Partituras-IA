/* ============================================================
   Gerador de Partituras IA — FASE 3O: catálogo de instrumentos.
   Somente nomenclatura p/ seleção (id canônico + nome PT + família).
   NÃO significa detecção: nada aqui afirma que o classificador
   detecta o instrumento. Exibição de "detectado" usa sempre os
   dados reais do backend. ES5, sem dependências.
   ============================================================ */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.GpiInstrumentCatalog = api;
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /* id canônico (underscores) → [nome PT, família]. */
  var ENTRIES = {
    piccolo: ['Flautim', 'woodwinds'],
    flute: ['Flauta', 'woodwinds'],
    alto_flute: ['Flauta alto', 'woodwinds'],
    oboe: ['Oboé', 'woodwinds'],
    english_horn: ['Corne inglês', 'woodwinds'],
    bassoon: ['Fagote', 'woodwinds'],
    contrabassoon: ['Contrafagote', 'woodwinds'],
    clarinet: ['Clarinete', 'woodwinds'],
    bass_clarinet: ['Clarinete baixo', 'woodwinds'],
    soprano_sax: ['Saxofone soprano', 'woodwinds'],
    alto_sax: ['Saxofone alto', 'woodwinds'],
    tenor_sax: ['Saxofone tenor', 'woodwinds'],
    baritone_sax: ['Saxofone barítono', 'woodwinds'],
    bass_sax: ['Saxofone baixo', 'woodwinds'],
    recorder: ['Flauta doce', 'woodwinds'],
    bagpipes: ['Gaita de foles', 'free_reed'],
    accordion: ['Acordeão', 'free_reed'],
    harmonica: ['Harmônica', 'free_reed'],
    melodica: ['Melódica', 'free_reed'],
    trumpet: ['Trompete', 'brass'],
    trombone: ['Trombone', 'brass'],
    french_horn: ['Trompa', 'brass'],
    tuba: ['Tuba', 'brass'],
    euphonium: ['Eufônio', 'brass'],
    cornet: ['Cornet', 'brass'],
    flugelhorn: ['Flugelhorn', 'brass'],
    marimba: ['Marimba', 'pitched_percussion'],
    xylophone: ['Xilofone', 'pitched_percussion'],
    vibraphone: ['Vibrafone', 'pitched_percussion'],
    glockenspiel: ['Glockenspiel', 'pitched_percussion'],
    timpani: ['Tímpano', 'pitched_percussion'],
    drum_kit: ['Bateria', 'unpitched_percussion'],
    snare: ['Caixa', 'unpitched_percussion'],
    bass_drum: ['Bumbo', 'unpitched_percussion'],
    cymbal: ['Prato', 'unpitched_percussion'],
    hi_hat: ['Hi-hat', 'unpitched_percussion'],
    tambourine: ['Pandeiro', 'unpitched_percussion'],
    shaker: ['Shaker', 'unpitched_percussion'],
    claves: ['Claves', 'unpitched_percussion'],
    cowbell: ['Cowbell', 'unpitched_percussion'],
    clap: ['Palma', 'body_percussion'],
    snap: ['Estalo de dedos', 'body_percussion'],
    stomp: ['Batida de pé', 'body_percussion'],
    beatbox: ['Beatbox', 'body_percussion'],
    soprano: ['Soprano', 'voices'],
    alto: ['Contralto', 'voices'],
    tenor: ['Tenor', 'voices'],
    baritone: ['Barítono', 'voices'],
    bass: ['Baixo (voz)', 'voices'],
    choir: ['Coro', 'voices'],
    lead_vocal: ['Voz principal', 'voices'],
    backing_vocal: ['Voz de apoio', 'voices'],
    piano: ['Piano', 'keyboards'],
    electric_piano: ['Piano elétrico', 'keyboards'],
    organ: ['Órgão', 'keyboards'],
    harpsichord: ['Cravo', 'keyboards'],
    synthesizer: ['Sintetizador', 'keyboards'],
    acoustic_guitar: ['Violão acústico', 'plucked_strings'],
    electric_guitar: ['Guitarra elétrica', 'plucked_strings'],
    classical_guitar: ['Violão clássico', 'plucked_strings'],
    electric_bass: ['Baixo elétrico', 'plucked_strings'],
    acoustic_bass: ['Baixo acústico', 'plucked_strings'],
    ukulele: ['Ukulele', 'plucked_strings'],
    banjo: ['Banjo', 'plucked_strings'],
    mandolin: ['Bandolim', 'plucked_strings'],
    harp: ['Harpa', 'plucked_strings'],
    sitar: ['Sitar', 'plucked_strings'],
    violin: ['Violino', 'bowed_strings'],
    viola: ['Viola', 'bowed_strings'],
    cello: ['Violoncelo', 'bowed_strings'],
    double_bass: ['Contrabaixo', 'bowed_strings']
  };

  var FAMILIES = ['woodwinds', 'free_reed', 'brass',
    'pitched_percussion', 'unpitched_percussion', 'body_percussion',
    'voices', 'keyboards', 'plucked_strings', 'bowed_strings'];

  function normalizeId(id) {
    if (typeof id !== 'string') return '';
    return id.trim().toLowerCase().replace(/-/g, '_');
  }

  function lookup(id) {
    var key = normalizeId(id);
    if (!key || !Object.prototype.hasOwnProperty.call(ENTRIES, key)) {
      return null;
    }
    return { id: key, name: ENTRIES[key][0], family: ENTRIES[key][1] };
  }

  function isKnown(id) {
    return lookup(id) !== null;
  }

  return {
    FAMILIES: FAMILIES,
    normalizeId: normalizeId,
    lookup: lookup,
    isKnown: isKnown
  };
}));
