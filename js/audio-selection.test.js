/* Testes da seleção de instrumentos FASE 3O (Node, DOM stub).
 * Uso: node js/audio-selection.test.js  (saída 0 = tudo OK)
 */
'use strict';
var S = require('./audio-selection.js');

var passed = 0;
function check(label, cond) {
  console.log((cond ? 'PASS' : 'FAIL') + ' ' + label);
  if (cond) { passed += 1; } else { process.exitCode = 1; }
}

function makeEl(tag) {
  var node = {
    tag: tag, className: '', textContent: '', hidden: false,
    disabled: false, checked: false, value: '', children: [],
    appendChild: function (c) { node.children.push(c); return c; },
    removeChild: function (c) {
      var i = node.children.indexOf(c);
      if (i >= 0) node.children.splice(i, 1);
      return c;
    },
    addEventListener: function () {},
    setAttribute: function () {},
    focus: function () {}
  };
  Object.defineProperty(node, 'firstChild', { get: function () { return node.children[0] || null; } });
  return node;
}

function stubDoc() {
  return { createElement: function (tag) { return makeEl(tag); } };
}

function container() {
  var doc = stubDoc();
  var c = makeEl('div');
  c.ownerDocument = doc;
  return c;
}

function textOf(node) {
  var out = (node.textContent || '') + '|' + (node.value || '');
  node.children.forEach(function (child) { out += '|' + textOf(child); });
  return out;
}

function resultOne() {
  return {
    title: 'Minha música',
    instruments: [{ id: 'electric_bass', name: 'Baixo elétrico', family: 'plucked_strings', confidence: 0.79, selected: true }],
    tracks: [{ track_id: 'track_01', name: 'Baixo', instrument_id: 'electric_bass', family: 'plucked_strings', confidence: 0.79, selected: true, ambiguous: false, note_count: 19 }]
  };
}

function resultMany() {
  return {
    title: null,
    instruments: [
      { id: 'piano', name: 'Piano', family: 'keyboards', confidence: 0.87, selected: true },
      { id: 'acoustic_guitar', name: 'Violão acústico', family: 'plucked_strings', confidence: 0.48, selected: false }
    ],
    tracks: [
      { track_id: 'track_01', name: 'Piano', instrument_id: 'piano', family: 'keyboards', confidence: 0.87, selected: true, ambiguous: false, note_count: 10 },
      { track_id: 'track_02', name: 'Faixa', instrument_id: null, family: 'unknown', confidence: null, selected: false, ambiguous: true, note_count: 5 }
    ]
  };
}

function jsonResp(status, body) {
  return { status: status, text: function () { return Promise.resolve(JSON.stringify(body)); } };
}

(async function () {
  // 1. resultado com 1 instrumento
  var st = S.createSelectionState(resultOne());
  check('1 instrumento', st.valid.length === 1 && st.selectedIds.length === 1 && st.unknownTracks.length === 0);
  // 2. vários instrumentos
  st = S.createSelectionState(resultMany());
  check('varios instrumentos', st.valid.length === 2 && st.selectedIds.length === 1);
  // 3-4. ambiguous/unknown preservados e não selecionáveis
  check('ambiguous/unknown', st.unknownTracks.length === 1 && S.toggle(st, 'inexistente') === false);
  // 5-6. selecionar/desmarcar
  S.toggle(st, 'acoustic_guitar');
  check('selecionar', S.isSelected(st, 'acoustic_guitar'));
  S.toggle(st, 'acoustic_guitar');
  check('desmarcar', !S.isSelected(st, 'acoustic_guitar'));
  // 7-8. todos (só válidos) / nenhum
  S.selectAll(st);
  check('selecionar todos', st.selectedIds.length === 2);
  S.deselectAll(st);
  check('desmarcar todos', st.selectedIds.length === 0);
  // 9. contador
  S.selectAll(st);
  check('contador', S.counterText(st) === '2 de 2 instrumentos selecionados');
  // 10-11. título inicial e edição
  check('titulo inicial', S.createSelectionState(resultOne()).title === 'Minha música');
  check('titulo default', S.createSelectionState(resultMany()).title === 'Música sem título');
  check('edicao titulo', S.validateTitle('  Nova  ').value === 'Nova');
  // 12-13. vazio e limite
  check('titulo vazio', S.validateTitle('   ').value === 'Música sem título');
  check('titulo limite', S.validateTitle(new Array(130).join('x')).ok === false && S.TITLE_MAX === 120);
  // 14. nenhum selecionado
  S.deselectAll(st);
  var v = S.validateSelection(st);
  check('nenhum selecionado', v.ok === false && /pelo menos um/.test(v.error));
  // 15-17. payload sem segredos/URLs
  S.selectAll(st);
  var payload = S.buildPayload(st, 'job-1', 'Título');
  var dump = JSON.stringify(payload);
  check('payload correto', payload.job_id === 'job-1' && payload.title === 'Título' &&
    payload.selected_instruments.length === 2 &&
    payload.selected_instruments[0].instrument_id === 'acoustic_guitar');
  var clean = ['secret', 'token', 'cookie', 'api_key', 'service_role', 'http', 'signed'].every(function (s) {
    return dump.toLowerCase().indexOf(s) < 0;
  });
  check('payload sem segredos/URL', clean);
  // 18. XSS no título (texto literal, sem HTML)
  var evil = '<script>alert(1)</script>';
  var c = container();
  S.mount(c, { title: evil, instruments: [], tracks: [] }, 'j', {});
  check('xss titulo', textOf(c).indexOf(evil) >= 0);
  var src = require('fs').readFileSync(__dirname + '/audio-selection.js', 'utf8');
  check('sem innerHTML', src.indexOf('innerHTML') < 0);
  // 19-20. múltiplas tracks / mesmo instrumento sem duplicar
  var multi = {
    title: 'X',
    instruments: [{ id: 'piano', name: 'Piano', family: 'keyboards', confidence: 0.8, selected: true }],
    tracks: [
      { track_id: 'track_01', name: 'P1', instrument_id: 'piano', family: 'keyboards', confidence: 0.8, selected: true, ambiguous: false, note_count: 5 },
      { track_id: 'track_02', name: 'P2', instrument_id: 'piano', family: 'keyboards', confidence: 0.7, selected: true, ambiguous: false, note_count: 7 }
    ]
  };
  st = S.createSelectionState(multi);
  check('mesmo instrumento sem duplicar', st.valid.length === 1);
  var p2 = S.buildPayload(st, 'j', 'T');
  check('track_ids rastreaveis', JSON.stringify(p2.selected_instruments[0].track_ids) === '["track_01","track_02"]');
  // submit: 200 e 422
  var okBody = { success: true, job_id: 'j', title: 'T', selected_instruments: [] };
  var fetch200 = function () { return Promise.resolve(jsonResp(200, okBody)); };
  var res = await S.submitSelection('j', st, 'T', fetch200);
  check('submit 200', res.success === true);
  var fetch422 = function () { return Promise.resolve(jsonResp(422, { success: false })); };
  var err422 = await S.submitSelection('j', st, 'T', fetch422).then(function () { return ''; }).catch(function (e) { return e.message; });
  check('submit 422', /inválid/.test(err422));
  // render monta cards + desabilita unknown
  var c2 = container();
  var mounted = S.mount(c2, resultMany(), 'j', {});
  var dump2 = textOf(c2);
  check('render cards', /Piano/.test(dump2) && /Instrumento não identificado/.test(dump2) && /Selecionar todos/.test(dump2));
  check('estado separado do original', (function () {
    var raw = resultMany();
    var before = JSON.stringify(raw);
    var s2 = S.createSelectionState(raw);
    S.toggle(s2, 'piano');
    return JSON.stringify(raw) === before;
  })());
  console.log('passed=' + passed);
})().catch(function (e) { console.error('FATAL', e && e.stack || e); process.exitCode = 1; });
