/* ============================================================
   Gerador de Partituras IA — FASE 3N: áudio → partitura (frontend).
   Conecta o pipeline real: upload multipart, polling de status e
   painel de resultado. JavaScript puro (ES5), sem dependências.
   Segredos nunca entram aqui; textos da API usam textContent.
   Núcleo puro + createClient(deps) permite testes em Node.
   ============================================================ */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.GpiAudioTranscribe = api;
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var STATES = {
    IDLE: 'IDLE',
    FILE_SELECTED: 'FILE_SELECTED',
    UPLOADING: 'UPLOADING',
    PROCESSING: 'PROCESSING',
    COMPLETED: 'COMPLETED',
    PARTIAL: 'PARTIAL',
    FAILED: 'FAILED'
  };

  var UPLOAD_URL = '/api/audio/upload';
  var STATUS_URL = '/api/transcription/status';
  var MAX_BYTES = 25 * 1024 * 1024; // espelha AudioConfig::DEFAULT_MAX_SIZE_MB
  var ACCEPTED_EXTENSIONS = ['mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac'];
  var POLL_INTERVAL_MS = 2000;
  var POLL_MAX_ELAPSED_MS = 600000; // 10 min
  var POLL_MAX_ERRORS = 6;

  /* Etapas do backend (contrato) → mensagem PT. Desconhecida cai no
     genérico seguro; porcentagem nunca é inventada. */
  var STAGE_MESSAGES = {
    queued: 'Na fila de processamento...',
    downloading: 'Enviando áudio...',
    decoding: 'Validando áudio...',
    separating: 'Separando instrumentos...',
    detecting_instruments: 'Detectando instrumentos...',
    extracting_notes: 'Transcrevendo...',
    quantizing: 'Analisando música...',
    analyzing: 'Analisando música...',
    building_score: 'Preparando resultado...',
    refining_ai: 'Refinando análise...',
    validating: 'Validando resultado...',
    completed: 'Concluído.',
    failed: 'Falha no processamento.'
  };

  var FAMILY_LABELS = {
    voices: 'Vozes',
    keyboards: 'Teclas',
    bowed_strings: 'Cordas friccionadas',
    plucked_strings: 'Cordas dedilhadas',
    brass: 'Metais',
    woodwinds: 'Madeiras',
    free_reed: 'Palhetas livres',
    pitched_percussion: 'Percussão afinada',
    unpitched_percussion: 'Percussão',
    body_percussion: 'Percussão corporal',
    unknown: 'Família não identificada'
  };

  function stageMessage(stage) {
    if (Object.prototype.hasOwnProperty.call(STAGE_MESSAGES, stage)) {
      return STAGE_MESSAGES[stage];
    }
    return 'Processando áudio...';
  }

  function errorForUpload(status) {
    if (status === 401) return 'Faça login para analisar uma música.';
    if (status === 400) return 'Arquivo inválido.';
    if (status === 413) return 'Arquivo muito grande (máximo 25 MB).';
    if (status === 429) return 'Limite diário de uploads atingido.';
    if (status === 0) return 'Não foi possível conectar ao servidor.';
    return 'Não foi possível enviar a música. Tente novamente.';
  }

  function errorForStatus(status) {
    if (status === 401) return 'Faça login para analisar uma música.';
    if (status === 400) return 'Arquivo inválido.';
    if (status === 404) return 'Análise não encontrada.';
    if (status === 0) return 'Não foi possível conectar ao servidor.';
    return 'Não foi possível processar a música. Tente novamente.';
  }

  function formatBytes(bytes) {
    if (typeof bytes !== 'number' || !(bytes >= 0)) return '—';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }

  function formatDuration(seconds) {
    if (typeof seconds !== 'number' || !(seconds >= 0)) return '—';
    var total = Math.floor(seconds);
    return Math.floor(total / 60) + ':' + String(total % 60).padStart(2, '0');
  }

  function formatPercent(value) {
    if (typeof value !== 'number' || !(value >= 0)) return null;
    return Math.max(0, Math.min(100, Math.round(value))) + '%';
  }

  function extensionOf(name) {
    if (typeof name !== 'string') return '';
    var i = name.lastIndexOf('.');
    if (i < 0) return '';
    return name.slice(i + 1).toLowerCase();
  }

  function validateFileMeta(name, size, maxBytes) {
    var ext = extensionOf(name);
    if (!name || ACCEPTED_EXTENSIONS.indexOf(ext) < 0) {
      return { ok: false, error: 'Formato não suportado. Use: ' + ACCEPTED_EXTENSIONS.join(', ') + '.' };
    }
    var limit = typeof maxBytes === 'number' ? maxBytes : MAX_BYTES;
    if (typeof size !== 'number' || !(size >= 0)) {
      return { ok: false, error: 'Arquivo inválido.' };
    }
    if (size > limit) {
      return { ok: false, error: 'Arquivo muito grande (máximo 25 MB).' };
    }
    if (size === 0) {
      return { ok: false, error: 'Arquivo inválido.' };
    }
    return { ok: true, error: null };
  }

  function safeText(value, fallback) {
    if (typeof value === 'string' && value !== '') return value;
    if (typeof value === 'number' && isFinite(value)) return String(value);
    return fallback === undefined ? '—' : fallback;
  }

  function confidencePercent(confidence) {
    if (typeof confidence !== 'number' || !(confidence >= 0)) return null;
    return Math.max(0, Math.min(100, Math.round(confidence * 100))) + '%';
  }

  function familyLabel(family) {
    if (Object.prototype.hasOwnProperty.call(FAMILY_LABELS, family)) {
      return FAMILY_LABELS[family];
    }
    return FAMILY_LABELS.unknown;
  }

  /* Extrai do contrato 3M somente o necessário p/ renderizar. */
  function summarizeResult(payload) {
    var result = payload && typeof payload === 'object' ? payload.result : null;
    if (!result || typeof result !== 'object') return null;
    return {
      title: typeof result.title === 'string' && result.title !== '' ? result.title : 'Sem título',
      duration: typeof result.duration_seconds === 'number' ? result.duration_seconds : null,
      bpm: typeof result.bpm === 'number' ? result.bpm : null,
      bpmConfidence: typeof result.bpm_confidence === 'number' ? result.bpm_confidence : null,
      key: result.key && typeof result.key === 'object' ? result.key : null,
      timeSignature: typeof result.time_signature === 'string' ? result.time_signature : null,
      confidence: typeof result.confidence === 'number' ? result.confidence : null,
      warnings: Array.isArray(result.warnings) ? result.warnings : [],
      instruments: Array.isArray(result.instruments) ? result.instruments : [],
      tracks: Array.isArray(result.tracks) ? result.tracks : [],
      noteCount: (result.statistics && typeof result.statistics.total_notes === 'number')
        ? result.statistics.total_notes : null
    };
  }

  function createClient(deps) {
    deps = deps || {};
    var fetchImpl = deps.fetchImpl || (typeof fetch !== 'undefined' ? fetch.bind(typeof window !== 'undefined' ? window : this) : null);
    var setTimer = deps.setTimeoutImpl || setTimeout;
    var clearTimer = deps.clearTimeoutImpl || clearTimeout;
    var now = deps.nowImpl || Date.now;
    var onChange = deps.onChange || function () {};

    var client = {
      state: STATES.IDLE,
      file: null,
      fileMeta: null,
      jobId: null,
      sourceId: null,
      timerId: null,
      pollStartedAt: 0,
      pollErrors: 0,
      lastSummary: null,

      setState: function (next) {
        this.state = next;
        onChange(next);
      },

      selectFile: function (file) {
        this.cancelPolling();
        if (!file) {
          this.file = null;
          this.fileMeta = null;
          this.setState(STATES.IDLE);
          return { ok: false, error: null };
        }
        var check = validateFileMeta(file.name, file.size, deps.maxBytes);
        if (!check.ok) {
          this.file = null;
          this.fileMeta = null;
          this.setState(STATES.IDLE);
          return check;
        }
        this.file = file;
        this.fileMeta = { name: file.name, size: file.size, type: file.type || '' };
        this.setState(STATES.FILE_SELECTED);
        return { ok: true, error: null, meta: this.fileMeta };
      },

      clear: function () {
        this.cancelPolling();
        this.file = null;
        this.fileMeta = null;
        this.jobId = null;
        this.sourceId = null;
        this.lastSummary = null;
        this.setState(STATES.IDLE);
      },

      cancelPolling: function () {
        if (this.timerId !== null) {
          try { clearTimer(this.timerId); } catch (e) { /* ignora */ }
          this.timerId = null;
        }
      },

      upload: function () {
        var self = this;
        if (!this.file || !fetchImpl || typeof FormData === 'undefined') {
          return Promise.reject(new Error('NO_FILE'));
        }
        this.setState(STATES.UPLOADING);
        var form = new FormData();
        form.append('audio', this.file, this.file.name);
        return fetchImpl(UPLOAD_URL, { method: 'POST', body: form, headers: { Accept: 'application/json' } })
          .then(function (response) {
            return response.text().then(function (text) {
              var data = null;
              try { data = JSON.parse(text); } catch (e) { data = null; }
              if (response.status === 201 && data && data.success === true && data.job_id) {
                self.sourceId = data.audio_source_id || null;
                self.jobId = data.job_id; // somente memória
                return { jobId: data.job_id, sourceId: self.sourceId };
              }
              var err = new Error(errorForUpload(response.status));
              err.httpStatus = response.status;
              throw err;
            });
          })
          .catch(function (err) {
            if (!err.httpStatus && (err.message === 'Failed to fetch' || err.message === 'NetworkError when attempting to fetch resource.')) {
              throw new Error(errorForUpload(0));
            }
            throw err instanceof Error ? err : new Error(errorForUpload(-1));
          });
      },

      analyze: function () {
        var self = this;
        if (this.state === STATES.UPLOADING || this.state === STATES.PROCESSING) {
          return Promise.reject(new Error('BUSY'));
        }
        return this.upload().then(function (res) {
          self.setState(STATES.PROCESSING);
          self.startPolling(res.jobId);
          return res;
        }).catch(function (err) {
          self.setState(self.file ? STATES.FILE_SELECTED : STATES.IDLE);
          throw err;
        });
      },

      startPolling: function (jobId) {
        this.cancelPolling();
        this.jobId = jobId;
        this.pollStartedAt = now();
        this.pollErrors = 0;
        this.setState(STATES.PROCESSING);
        this.pollOnce();
      },

      pollOnce: function () {
        var self = this;
        if (!this.jobId || !fetchImpl) return;
        var url = STATUS_URL + '?job_id=' + encodeURIComponent(this.jobId);
        fetchImpl(url, { headers: { Accept: 'application/json' } })
          .then(function (response) {
            return response.text().then(function (text) {
              return { status: response.status, text: text };
            });
          })
          .then(function (res) {
            self.pollErrors = 0;
            self.handlePollResponse(res.status, res.text);
          })
          .catch(function () {
            self.pollErrors += 1;
            if (self.pollErrors >= POLL_MAX_ERRORS) {
              self.finishFailed(errorForStatus(0));
              return;
            }
            var delay = Math.min(POLL_INTERVAL_MS * Math.pow(2, self.pollErrors - 1), 10000);
            self.schedule(delay);
          });
      },

      schedule: function (delay) {
        var self = this;
        this.cancelPolling();
        if (now() - this.pollStartedAt > POLL_MAX_ELAPSED_MS) {
          this.finishFailed('Tempo de análise esgotado. Tente novamente.');
          return;
        }
        this.timerId = setTimer(function () {
          self.timerId = null;
          self.pollOnce();
        }, delay);
      },

      handlePollResponse: function (httpStatus, text) {
        var data = null;
        try { data = JSON.parse(text); } catch (e) { data = null; }
        if (httpStatus === 401 || httpStatus === 404 || httpStatus === 400) {
          this.finishFailed(errorForStatus(httpStatus), httpStatus);
          return;
        }
        if (httpStatus !== 200 || !data || data.success !== true) {
          this.finishFailed(errorForStatus(httpStatus));
          return;
        }
        var status = data.status;
        if (status === 'completed' || status === 'partial') {
          var summary = summarizeResult(data);
          if (!summary) {
            this.finishFailed('Resultado indisponível. Tente novamente.');
            return;
          }
          this.lastSummary = summary;
          this.cancelPolling();
          this.setState(status === 'completed' ? STATES.COMPLETED : STATES.PARTIAL);
          if (typeof this.onResult === 'function') this.onResult(summary, status);
          return;
        }
        if (status === 'failed') {
          var message = (data.job && typeof data.job.error_message === 'string' && data.job.error_message !== '')
            ? data.job.error_message
            : 'Não foi possível processar a música. Tente novamente.';
          this.finishFailed(message);
          return;
        }
        if (typeof this.onProgress === 'function') {
          this.onProgress({
            status: status,
            progress: typeof data.progress === 'number' ? data.progress : null,
            stage: typeof data.current_stage === 'string' ? data.current_stage : null
          });
        }
        this.schedule(POLL_INTERVAL_MS);
      },

      finishFailed: function (message, httpStatus) {
        this.cancelPolling();
        this.setState(STATES.FAILED);
        if (typeof this.onError === 'function') this.onError(message, httpStatus);
      },

      onProgress: null,
      onResult: null,
      onError: null
    };

    return client;
  }

  /* ---------- Wiring DOM (navegador) ----------
     Somente textContent/createElement/removeChild; nenhum HTML
     injetado via string, nenhum
     segredo, nenhum token em storage. Sem seção no DOM = no-op. */
  var activeDoc = null;
  function el(tag, cls, text) {
    var doc = activeDoc || (typeof document !== 'undefined' ? document : null);
    var node = doc.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function clearChildren(node) {
    if (!node) return;
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function setVisible(node, visible) {
    if (node) node.hidden = !visible;
  }

  function initSection(doc) {
    doc = doc || (typeof document !== 'undefined' ? document : null);
    if (!doc) return null;
    var root = doc.getElementById('audio-transcrever');
    if (!root) return null;
    var fileInput = doc.getElementById('audio2-file');
    var fileInfo = doc.getElementById('audio2-fileinfo');
    var analyzeBtn = doc.getElementById('audio2-analyze');
    var clearBtn = doc.getElementById('audio2-clear');
    var feedback = doc.getElementById('audio2-feedback');
    var progressBox = doc.getElementById('audio2-progress');
    var stageEl = doc.getElementById('audio2-stage');
    var pctEl = doc.getElementById('audio2-pct');
    var resultBox = doc.getElementById('audio2-result');
    var loginBtn = doc.getElementById('audio2-login');
    if (!fileInput || !analyzeBtn) return null;
    activeDoc = doc;

    var client = createClient({});
    var lastFileLabel = '';

    function showFeedback(message, kind) {
      feedback.hidden = false;
      feedback.textContent = message;
      feedback.classList.toggle('gen-feedback--error', kind === 'error');
      feedback.classList.toggle('gen-feedback--success', kind === 'success');
      setVisible(loginBtn, kind === 'login');
    }

    function hideFeedback() {
      feedback.hidden = true;
      feedback.textContent = '';
      setVisible(loginBtn, false);
    }

    function renderIdle() {
      setVisible(resultBox, false);
      setVisible(progressBox, false);
      clearChildren(resultBox);
      var selectionBox = doc.getElementById('audio2-selection');
      if (selectionBox) {
        clearChildren(selectionBox);
        setVisible(selectionBox, false);
      }
      analyzeBtn.disabled = true;
      setVisible(clearBtn, false);
      setVisible(fileInfo, false);
    }

    /* Seleção de instrumentos (3O): camada separada sobre o summary,
       sem tocar na análise original. Módulo opcional. */
    function mountSelection(summary) {
      var selectionBox = doc.getElementById('audio2-selection');
      if (!selectionBox) return;
      clearChildren(selectionBox);
      setVisible(selectionBox, false);
      var selectionApi = (typeof window !== 'undefined' && window.GpiAudioSelection)
        ? window.GpiAudioSelection : null;
      if (!selectionApi || !summary) return;
      var mounted = selectionApi.mount(selectionBox, summary, client.jobId, {
        onSubmit: function (state, title) {
          return selectionApi.submitSelection(client.jobId, state, title);
        },
        onSaved: function () {
          showFeedback('Seleção salva. A geração da partitura final chega na próxima fase.', 'success');
        }
      });
      if (mounted) setVisible(selectionBox, true);
    }

    function renderFileSelected(meta) {
      renderIdle();
      fileInfo.textContent = meta.name + ' · ' + formatBytes(meta.size) +
        (meta.type ? ' · ' + meta.type : '');
      setVisible(fileInfo, true);
      analyzeBtn.disabled = false;
      setVisible(clearBtn, true);
      analyzeBtn.focus();
    }

    function renderProgress(info) {
      setVisible(progressBox, true);
      var label = stageMessage(info.stage) + (info.stage === 'failed' || info.stage === 'completed' ? '' : '');
      stageEl.textContent = label;
      var pct = formatPercent(info.progress);
      pctEl.textContent = pct === null ? '' : pct;
    }

    function metaRow(term, value) {
      var dt = el('dt', null, term);
      var dd = el('dd', null, value);
      return [dt, dd];
    }

    function renderResult(summary, status) {
      setVisible(progressBox, false);
      clearChildren(resultBox);
      var title = el('h3', 'audio2__result-title', summary.title);
      resultBox.appendChild(title);
      var state = el('p', 'audio2__result-state',
        status === 'completed' ? 'Análise concluída.' : 'Análise parcial: alguns itens ficaram indeterminados.');
      resultBox.appendChild(state);
      var dl = el('dl', 'audio2__meta');
      var keyText = summary.key ? summary.key.tonic + ' ' + summary.key.mode : '—';
      if (summary.key && typeof summary.key.confidence === 'number') {
        keyText += ' (' + confidencePercent(summary.key.confidence) + ')';
      }
      var bpmText = summary.bpm === null ? '—' : String(summary.bpm) + ' BPM';
      if (typeof summary.bpmConfidence === 'number') {
        bpmText += ' (' + confidencePercent(summary.bpmConfidence) + ')';
      }
      metaRow('Duração', formatDuration(summary.duration)).forEach(function (n) { dl.appendChild(n); });
      metaRow('BPM', bpmText).forEach(function (n) { dl.appendChild(n); });
      metaRow('Tonalidade', keyText).forEach(function (n) { dl.appendChild(n); });
      metaRow('Compasso', summary.timeSignature === null ? '—' : summary.timeSignature).forEach(function (n) { dl.appendChild(n); });
      resultBox.appendChild(dl);

      var instTitle = el('h4', 'audio2__subtitle', 'Instrumentos detectados');
      resultBox.appendChild(instTitle);
      var instList = el('ul', 'audio2__list');
      if (!summary.instruments.length) {
        instList.appendChild(el('li', null, 'Nenhum instrumento identificado com confiança suficiente.'));
      }
      summary.instruments.forEach(function (inst) {
        var li = el('li', 'audio2__item');
        var conf = confidencePercent(inst.confidence);
        li.appendChild(el('strong', null, safeText(inst.name, 'Possível instrumento')));
        li.appendChild(el('span', null, ' · ' + familyLabel(inst.family)));
        if (conf !== null) li.appendChild(el('span', null, ' · ' + conf));
        li.appendChild(el('span', 'audio2__badge', inst.ambiguous ? 'Possível instrumento' : 'Detectado'));
        instList.appendChild(li);
      });
      resultBox.appendChild(instList);

      var trackTitle = el('h4', 'audio2__subtitle', 'Faixas');
      resultBox.appendChild(trackTitle);
      var trackList = el('ul', 'audio2__list');
      summary.tracks.forEach(function (track) {
        var li = el('li', 'audio2__item');
        var conf = confidencePercent(track.confidence);
        var label = safeText(track.name, safeText(track.instrument_id, 'Faixa'));
        li.appendChild(el('strong', null, label));
        li.appendChild(el('span', null, ' · ' + familyLabel(track.family)));
        if (conf !== null) li.appendChild(el('span', null, ' · ' + conf));
        var count = (typeof track.note_count === 'number') ? track.note_count : 0;
        li.appendChild(el('span', null, ' · ' + count + (count === 1 ? ' nota' : ' notas')));
        trackList.appendChild(li);
      });
      resultBox.appendChild(trackList);

      var noteCount = (typeof summary.noteCount === 'number') ? summary.noteCount : null;
      resultBox.appendChild(el('p', 'audio2__notes',
        noteCount === null ? 'Notas detectadas: —' : noteCount + (noteCount === 1 ? ' nota detectada' : ' notas detectadas')));
      var preview = el('div', 'audio2__preview');
      preview.setAttribute('aria-label', 'Prévia da partitura (disponível em breve)');
      preview.appendChild(el('p', null, 'Prévia da partitura — disponível em breve.'));
      resultBox.appendChild(preview);

      if (summary.warnings.length) {
        var warnBox = el('div', 'audio2__warnings');
        warnBox.appendChild(el('h4', 'audio2__subtitle', 'Atenção'));
        var warnList = el('ul', 'audio2__list');
        summary.warnings.forEach(function (warning) {
          var text = (warning && typeof warning === 'object')
            ? (warning.message || warning.code || 'Aviso.')
            : String(warning);
          warnList.appendChild(el('li', null, text));
        });
        warnBox.appendChild(warnList);
        resultBox.appendChild(warnBox);
      }
      setVisible(resultBox, true);
      title.setAttribute('tabindex', '-1');
      title.focus({ preventScroll: true });
    }

    client.onProgress = function (info) { renderProgress(info); };
    client.onResult = function (summary, status) {
      hideFeedback();
      analyzeBtn.disabled = false;
      renderResult(summary, status);
      mountSelection(summary);
    };
    client.onError = function (message) {
      setVisible(progressBox, false);
      analyzeBtn.disabled = false;
      var isLogin = message === errorForStatus(401) || message === errorForUpload(401);
      showFeedback(message, isLogin ? 'login' : 'error');
    };

    fileInput.addEventListener('change', function () {
      hideFeedback();
      var file = fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;
      var res = client.selectFile(file);
      if (!file) { renderIdle(); return; }
      lastFileLabel = file.name || '';
      if (!res.ok) {
        renderIdle();
        showFeedback(res.error, 'error');
        fileInput.focus();
        return;
      }
      renderFileSelected(res.meta);
    });

    clearBtn.addEventListener('click', function () {
      fileInput.value = '';
      client.clear();
      hideFeedback();
      renderIdle();
      fileInput.focus();
    });

    analyzeBtn.addEventListener('click', function () {
      if (client.state === STATES.UPLOADING || client.state === STATES.PROCESSING) return;
      hideFeedback();
      setVisible(resultBox, false);
      clearChildren(resultBox);
      var selectionBox = doc.getElementById('audio2-selection');
      if (selectionBox) {
        clearChildren(selectionBox);
        setVisible(selectionBox, false);
      }
      analyzeBtn.disabled = true;
      showFeedback('Enviando áudio...', 'success');
      setVisible(progressBox, true);
      stageEl.textContent = stageMessage('downloading');
      pctEl.textContent = '';
      client.analyze().catch(function (err) {
        setVisible(progressBox, false);
        analyzeBtn.disabled = false;
        var message = (err && err.message && err.message !== 'NO_FILE' && err.message !== 'BUSY')
          ? err.message : 'Não foi possível enviar a música. Tente novamente.';
        var isLogin = message === errorForUpload(401);
        showFeedback(message, isLogin ? 'login' : 'error');
      });
    });

    if (loginBtn) {
      loginBtn.addEventListener('click', function () {
        var opener = doc.querySelector('.js-open-auth');
        if (opener && opener.click) opener.click();
      });
    }

    renderIdle();
    return client;
  }

  /* ---------- Bootstrap (navegador) ---------- */
  if (typeof document !== 'undefined' && typeof window !== 'undefined') {
    var bootstrap = function () { initSection(document); };
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', bootstrap);
    } else {
      bootstrap();
    }
  }

  return {
    STATES: STATES,    UPLOAD_URL: UPLOAD_URL,
    STATUS_URL: STATUS_URL,
    MAX_BYTES: MAX_BYTES,
    ACCEPTED_EXTENSIONS: ACCEPTED_EXTENSIONS,
    POLL_INTERVAL_MS: POLL_INTERVAL_MS,
    STAGE_MESSAGES: STAGE_MESSAGES,
    stageMessage: stageMessage,
    errorForUpload: errorForUpload,
    errorForStatus: errorForStatus,
    formatBytes: formatBytes,
    formatDuration: formatDuration,
    formatPercent: formatPercent,
    validateFileMeta: validateFileMeta,
    confidencePercent: confidencePercent,
    familyLabel: familyLabel,
    safeText: safeText,
    summarizeResult: summarizeResult,
    createClient: createClient,
    initSection: initSection
  };
}));
