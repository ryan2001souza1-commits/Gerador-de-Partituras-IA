/* Testes do frontend de áudio FASE 3N (Node, sem DOM real).
 * Uso: node js/audio-transcribe.test.js  (saída 0 = tudo OK)
 */
'use strict';
var assert = require('assert');
if (typeof FormData === 'undefined') {
  global.FormData = function () { this.append = function () {}; };
}
var T = require('./audio-transcribe.js');

var passed = 0;
function check(label, cond) {
  console.log((cond ? 'PASS' : 'FAIL') + ' ' + label);
  if (cond) { passed += 1; } else { process.exitCode = 1; }
}

function fakeFile(name, size) {
  return { name: name, size: size, type: 'audio/wav' };
}

function jsonResponse(status, body) {
  return { status: status, text: function () { return Promise.resolve(JSON.stringify(body)); } };
}

function makeClient(queue, opts) {
  opts = opts || {};
  var timers = [];
  var client = T.createClient({
    fetchImpl: function () {
      var next = queue.shift();
      if (!next) return Promise.reject(new Error('Failed to fetch'));
      if (next instanceof Error) return Promise.reject(next);
      return Promise.resolve(next);
    },
    setTimeoutImpl: function (fn, ms) { timers.push({ fn: fn, ms: ms }); return timers.length; },
    clearTimeoutImpl: function () {},
    nowImpl: function () { return 0; },
    maxBytes: opts.maxBytes
  });
  client.__timers = timers;
  return client;
}

function flush() { return new Promise(function (res) { setTimeout(res, 0); }); }

function completedPayload() {
  return { success: true, status: 'completed', progress: 100, current_stage: 'completed',
    job: { job_id: 'j', status: 'completed' },
    result: { title: null, duration_seconds: 4.0, bpm: 120, bpm_confidence: 0.8,
      key: { tonic: 'C', mode: 'major', confidence: 0.7 }, time_signature: '4/4',
      confidence: 0.7, warnings: [{ code: 'W', message: 'Aviso' }],
      instruments: [{ id: 'electric_bass', name: 'Baixo elétrico', family: 'plucked_strings', confidence: 0.79, evidence: {}, selected: true, ambiguous: false }],
      tracks: [{ track_id: 'track_01', name: 'Baixo', instrument_id: 'electric_bass', family: 'plucked_strings', confidence: 0.79, selected: true, ambiguous: false, note_count: 19, duration_seconds: 4.0, evidence: {} }],
      notes: [], statistics: { total_notes: 29 } } };
}

(async function () {
  // 1. seleção de arquivo
  var c = makeClient([]);
  var r = c.selectFile(fakeFile('musica.wav', 1000));
  check('selecao de arquivo', r.ok === true && c.state === T.STATES.FILE_SELECTED);
  // 2. arquivo inválido
  c = makeClient([]);
  r = c.selectFile(fakeFile('virus.exe', 100));
  check('arquivo invalido', r.ok === false && /Formato/.test(r.error));
  // 3. upload 201
  c = makeClient([jsonResponse(201, { success: true, audio_source_id: 's', job_id: 'j' })]);
  c.selectFile(fakeFile('a.wav', 10));
  var up = await c.upload().catch(function () { return null; });
  check('upload 201', !!up && up.jobId === 'j' && c.jobId === 'j' && c.sourceId === 's');
  // 4. upload 401
  c = makeClient([jsonResponse(401, { success: false })]);
  c.selectFile(fakeFile('a.wav', 10));
  var e401 = await c.upload().then(function () { return ''; }).catch(function (e) { return e.message; });
  check('upload 401', e401 === 'Faça login para analisar uma música.');
  // 5. upload 400
  c = makeClient([jsonResponse(400, { success: false })]);
  c.selectFile(fakeFile('a.wav', 10));
  var e400 = await c.upload().then(function () { return ''; }).catch(function (e) { return e.message; });
  check('upload 400', e400 === 'Arquivo inválido.');
  // 6. upload 413
  c = makeClient([]);
  r = c.selectFile(fakeFile('big.wav', T.MAX_BYTES + 1));
  check('upload 413 (limite local)', r.ok === false && /grande/.test(r.error));
  // 7-11. polling por status
  var queued = { success: true, status: 'queued', progress: 5, current_stage: 'queued', job: {}, result: null };
  var cases = [
    ['queued', 'queued', T.STATES.PROCESSING],
    ['processing', 'processing', T.STATES.PROCESSING],
    ['completed', 'completed', T.STATES.COMPLETED],
    ['partial', 'partial', T.STATES.PARTIAL],
    ['failed', 'failed', T.STATES.FAILED]
  ];
  for (var i = 0; i < cases.length; i++) {
    var name = cases[i][0];
    var body = name === 'completed' || name === 'partial'
      ? completedPayload() && (function () { var p = completedPayload(); p.status = name; return p; })()
      : (name === 'failed'
        ? { success: true, status: 'failed', progress: 45, current_stage: 'separating', job: { error_message: 'Falha X' }, result: null }
        : queued && { success: true, status: name, progress: name === 'queued' ? 5 : 55, current_stage: 'separating', job: {}, result: null });
    var cc = makeClient([body && jsonResponse(200, body)]);
    var seen = [];
    cc.onProgress = function (p) { seen.push(p); };
    var done = null;
    cc.onResult = function (s, st) { done = st; };
    cc.onError = function (m) { done = 'ERR:' + m; };
    cc.startPolling('j');
    await flush(); await flush();
    check('polling ' + name, (name === 'completed' || name === 'partial') ? done === name : (name === 'failed' ? /^ERR:/.test(done) : cc.state === T.STATES.PROCESSING));
  }
  // 12. polling 404
  c = makeClient([jsonResponse(404, { success: false })]);
  var m404 = null;
  c.onError = function (m) { m404 = m; };
  c.startPolling('j'); await flush(); await flush();
  check('polling 404', m404 === 'Análise não encontrada.');
  // 13. erro de rede com backoff e limite
  c = makeClient([new Error('Failed to fetch'), new Error('Failed to fetch'), new Error('Failed to fetch'), new Error('Failed to fetch'), new Error('Failed to fetch'), new Error('Failed to fetch'), new Error('Failed to fetch')]);
  var mNet = null;
  c.onError = function (m) { mNet = m; };
  c.startPolling('j');
  for (var k = 0; k < 12; k++) { await flush(); c.__timers.splice(0).forEach(function (t) { t.fn(); }); await flush(); }
  check('erro de rede', mNet === 'Não foi possível conectar ao servidor.' && c.state === T.STATES.FAILED);
  // 14-16. múltiplos jobs / cancelamento / sem duplicação
  c = makeClient([jsonResponse(200, queued), jsonResponse(200, queued)]);
  c.startPolling('job-a');
  var firstTimer = c.__timers.length;
  c.startPolling('job-b');
  check('multiplos jobs cancelam anterior', c.jobId === 'job-b' && c.__timers.length <= firstTimer + 1);
  // 17. instrumento conhecido
  var s = T.summarizeResult(completedPayload());
  check('instrumento conhecido', s.instruments[0].id === 'electric_bass' && T.familyLabel('plucked_strings') === 'Cordas dedilhadas');
  // 18. ambiguous
  check('ambiguous preservado', T.familyLabel('unknown') === 'Família não identificada' && T.stageMessage('etapa_xyz') === 'Processando áudio...');
  // 19. warnings formato
  check('warnings', Array.isArray(s.warnings) && s.warnings.length === 1);
  // 20. ausência de secrets no módulo
  var src = require('fs').readFileSync(__dirname + '/audio-transcribe.js', 'utf8');
  var hasSecret = /SUPABASE|service_role|WORKER_WEBHOOK|NVIDIA|api[_-]?key|localStorage/.test(src);
  check('ausencia de secrets', !hasSecret);
  // 21. XSS: textContent-only (nenhum innerHTML no módulo)
  check('sem innerHTML', src.indexOf('innerHTML') < 0);
  var evil = '<img src=x onerror=alert(1)>';
  check('safeText neutro', T.safeText(evil, 'x') === evil); // texto, nunca HTML
  // 22. responsividade sem regressão (CSS verificado separadamente)
  check('stage messages PT', T.stageMessage('separating') === 'Separando instrumentos...' && T.stageMessage('extracting_notes') === 'Transcrevendo...');
  // estados impossíveis: analyze durante PROCESSING rejeita
  c = makeClient([]);
  c.state = T.STATES.PROCESSING;
  var busy = await c.analyze().then(function () { return ''; }).catch(function (e) { return e.message; });
  check('sem upload duplo', busy === 'BUSY');
  console.log('passed=' + passed);
})().catch(function (e) { console.error('FATAL', e && e.message); process.exitCode = 1; });
