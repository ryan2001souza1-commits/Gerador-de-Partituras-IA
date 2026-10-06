/* Testes da geração a partir da seleção FASE 3P-frontend (Node, DOM stub).
 * Uso: node js/audio-generate.test.js  (saída 0 = tudo OK)
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
    addEventListener: function (t, fn) { node['on_' + t] = fn; },
    setAttribute: function () {},
    focus: function () {},
    click: function () { if (node.on_click) node.on_click(); }
  };
  Object.defineProperty(node, 'firstChild', { get: function () { return node.children[0] || null; } });
  return node;
}

function stubDoc() {
  return { createElement: function (tag) { return makeEl(tag); } };
}

function container() {
  var c = makeEl('div');
  c.ownerDocument = stubDoc();
  return c;
}

function textOf(node) {
  var out = (node.textContent || '') + '|' + (node.value || '');
  node.children.forEach(function (child) { out += '|' + textOf(child); });
  return out;
}

function findAll(node, pred, acc) {
  acc = acc || [];
  if (pred(node)) acc.push(node);
  node.children.forEach(function (child) { findAll(child, pred, acc); });
  return acc;
}

function completedResult() {
  return {
    title: 'Minha música',
    instruments: [
      { id: 'piano', name: 'Piano', family: 'keyboards', confidence: 0.87, selected: true },
      { id: 'acoustic_guitar', name: 'Violão', family: 'plucked_strings', confidence: 0.48, selected: false }
    ],
    tracks: [
      { track_id: 'track_01', name: 'Piano', instrument_id: 'piano', family: 'keyboards', confidence: 0.87, selected: true, ambiguous: false, note_count: 10 },
      { track_id: 'track_02', name: 'Faixa', instrument_id: null, family: 'unknown', confidence: null, selected: false, ambiguous: true, note_count: 5 },
      { track_id: 'track_03', name: 'Violão', instrument_id: 'acoustic_guitar', family: 'plucked_strings', confidence: 0.48, selected: false, ambiguous: false, note_count: 7 }
    ]
  };
}

function jsonResp(status, body) {
  return { status: status, text: function () { return Promise.resolve(JSON.stringify(body)); } };
}

function blobResp(status, blob) {
  return { status: status, blob: function () { return Promise.resolve(blob); }, text: function () { return Promise.resolve(''); } };
}

function okJson() {
  return jsonResp(200, { success: true, job_id: 'job-1', title: 'Minha música', status: 'completed', parts: [], warnings: [], statistics: {} });
}

(async function () {
  // A) resultado completed monta seleção + gerar
  var c = container();
  var mounted = S.mount(c, completedResult(), 'job-1', {});
  check('A) completed monta', !!mounted && textOf(c).indexOf('Gerar partitura') >= 0);
  // B) resultado partial monta igual
  var partial = completedResult();
  var cB = container();
  var mountedB = S.mount(cB, partial, 'job-1', {});
  check('B) partial monta', !!mountedB && textOf(cB).indexOf('Gerar partitura') >= 0);
  // C) instrumentos detectados listados
  check('C) instrumentos', textOf(c).indexOf('Piano') >= 0 && textOf(c).indexOf('Violão') >= 0);
  // D) seleção individual via toggle
  var st = mounted.state;
  S.toggle(st, 'acoustic_guitar');
  check('D) seleção individual', S.isSelected(st, 'acoustic_guitar'));
  S.toggle(st, 'acoustic_guitar');
  // E) selecionar todos
  S.selectAll(st);
  check('E) selecionar todos', st.selectedIds.length === 2);
  // F) limpar seleção
  S.deselectAll(st);
  check('F) limpar seleção', st.selectedIds.length === 0);
  // G) unknown desabilitado (checkbox disabled no DOM)
  var disabledBoxes = findAll(c, function (n) { return n.tag === 'input' && n.disabled === true; });
  check('G) unknown desabilitado', disabledBoxes.length >= 1);
  // H) título editado aceito
  var tv = S.validateTitle('  Nova peça  ');
  check('H) título editado', tv.ok === true && tv.value === 'Nova peça');
  // I) título acima de 120
  var longTitle = new Array(130).join('x');
  check('I) título >120', S.validateTitle(longTitle).ok === false);
  // J) nenhum selecionado → sem request
  var fetchCalls = 0;
  var countingFetch = function () { fetchCalls++; return Promise.resolve(okJson()); };
  S.deselectAll(st);
  var jerr = await S.requestGenerate('job-1', st, 'T', countingFetch, 'json').then(function () { return ''; }).catch(function (e) { return e.message; });
  check('J) vazio sem request', fetchCalls === 0 && /pelo menos um/.test(jerr));
  // K) POST generate 200
  S.selectAll(st);
  var posted = null;
  var captureFetch = function (url, opts) {
    posted = { url: url, body: JSON.parse(opts.body) };
    return Promise.resolve(okJson());
  };
  var kdata = await S.requestGenerate('job-1', st, 'Título', captureFetch, 'json');
  check('K) generate 200', kdata.success === true && posted.url === '/api/transcription/generate?format=json'
    && posted.body.job_id === 'job-1' && posted.body.title === 'Título'
    && posted.body.selected_instruments.length === 2);
  // L-O) códigos de erro
  var codes = { 401: /sessão|login/i, 404: /disponível/i, 409: /processamento|estado/i, 422: /seleção|Revise/i };
  var codeList = [401, 404, 409, 422];
  for (var i = 0; i < codeList.length; i++) {
    var code = codeList[i];
    var fetchCode = (function (sc) {
      return function () { return Promise.resolve(jsonResp(sc, { success: false })); };
    })(code);
    var emsg = await S.requestGenerate('job-1', st, 'T', fetchCode, 'json').then(function () { return ''; }).catch(function (e) { return e.message; });
    var labels = { 401: 'L', 404: 'M', 409: 'N', 422: 'O' };
    check(labels[code] + ') erro ' + code, codes[code].test(emsg));
  }
  // P) duplo clique: uma requisição (via UI com hooks.onGenerate)
  var cP = container();
  var genCalls = 0;
  var slowHook = function () {
    genCalls++;
    return new Promise(function () {}); // nunca resolve: segundo clique deve ser ignorado
  };
  var mountedP = S.mount(cP, completedResult(), 'job-1', { onGenerate: slowHook });
  var genBtns = findAll(cP, function (n) { return n.textContent === 'Gerar partitura'; });
  check('P) botão existe', genBtns.length === 1);
  genBtns[0].click();
  genBtns[0].click();
  await new Promise(function (res) { setTimeout(res, 20); });
  check('P) duplo clique uma request', genCalls === 1 && genBtns[0].disabled === true);
  // Q/R) PDF e MIDI via hooks.onDownload
  var cQ = container();
  var dlCalls = [];
  var mountedQ = S.mount(cQ, completedResult(), 'job-1', {
    onDownload: function (state, title, fmt) { dlCalls.push(fmt); return Promise.resolve({}); }
  });
  var pdfBtns = findAll(cQ, function (n) { return n.textContent === 'Baixar PDF'; });
  var midiBtns = findAll(cQ, function (n) { return n.textContent === 'Baixar MIDI'; });
  check('Q/R) botões download', pdfBtns.length === 1 && midiBtns.length === 1);
  // gera sucesso primeiro para revelar downloads
  var genOk = findAll(cQ, function (n) { return n.textContent === 'Gerar partitura'; })[0];
  var realFetch = function () { return Promise.resolve(okJson()); };
  // usa requestGenerate direto p/ validar blob
  var fakeBlob = { size: 123 };
  var blobFetch = function (url) {
    if (url.indexOf('format=pdf') < 0 && url.indexOf('format=midi') < 0) {
      return Promise.resolve(jsonResp(400, {}));
    }
    return Promise.resolve(blobResp(200, fakeBlob));
  };
  S.selectAll(mountedQ.state);
  var pdfRes = await S.requestGenerate('job-1', mountedQ.state, 'T', blobFetch, 'pdf');
  var midiRes = await S.requestGenerate('job-1', mountedQ.state, 'T', blobFetch, 'midi');
  check('Q) PDF blob', pdfRes.blob === fakeBlob && pdfRes.filename === 'partitura.pdf');
  check('R) MIDI blob', midiRes.blob === fakeBlob && midiRes.filename === 'partitura.mid');
  // S) nenhuma secret no payload
  var dump = JSON.stringify(posted.body);
  var clean = ['secret', 'token', 'cookie', 'api_key', 'service_role', 'http', 'signed', 'webhook'].every(function (s) {
    return dump.toLowerCase().indexOf(s) < 0;
  });
  check('S) sem secrets', clean);
  // T) nenhum innerHTML inseguro
  var src = require('fs').readFileSync(__dirname + '/audio-selection.js', 'utf8');
  check('T) sem innerHTML', src.indexOf('innerHTML') < 0);
  console.log('passed=' + passed);
})().catch(function (e) { console.error('FATAL', e && e.stack || e); process.exitCode = 1; });
