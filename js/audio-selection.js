/* ============================================================
   Gerador de Partituras IA — FASE 3O: seleção de instrumentos.
   Opera sobre o resultado 3M já renderizado: nunca altera a análise
   original (selectionState separado), nunca inventa instrumentos,
   nunca seleciona unknown/ambiguous automaticamente. Textos via
   textContent; sem segredos no payload. ES5, sem dependências.
   ============================================================ */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.GpiAudioSelection = api;
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var TITLE_MAX = 120;
  var TITLE_DEFAULT = 'Música sem título';
  var SELECT_URL = '/api/transcription/select';
  var GENERATE_URL = '/api/transcription/generate';
  var GENERATE_FORMATS = ['json', 'midi', 'pdf'];

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

  function confidencePercent(confidence) {
    if (typeof confidence !== 'number' || !(confidence >= 0)) return null;
    return Math.max(0, Math.min(100, Math.round(confidence * 100))) + '%';
  }

  function initialTitle(result) {
    var title = result && typeof result.title === 'string' ? result.title.trim() : '';
    if (title === '' || title === 'Sem título') return TITLE_DEFAULT;
    return title.slice(0, TITLE_MAX);
  }

  /* Estado separado da análise original (nunca a muta). */
  function createSelectionState(result) {
    result = result && typeof result === 'object' ? result : {};
    var instruments = Array.isArray(result.instruments) ? result.instruments : [];
    var tracks = Array.isArray(result.tracks) ? result.tracks : [];
    var valid = [];
    var seen = {};
    instruments.forEach(function (inst) {
      if (!inst || typeof inst.id !== 'string' || inst.id === '') return;
      if (seen[inst.id]) return;
      seen[inst.id] = true;
      valid.push({
        id: inst.id,
        name: typeof inst.name === 'string' && inst.name !== '' ? inst.name : inst.id,
        family: typeof inst.family === 'string' ? inst.family : 'unknown',
        confidence: typeof inst.confidence === 'number' ? inst.confidence : null,
        selected: inst.selected === true
      });
    });
    var unknownTracks = tracks.filter(function (track) {
      return track && typeof track === 'object' &&
        (track.instrument_id === null || track.instrument_id === undefined || track.instrument_id === '');
    }).map(function (track) {
      return {
        track_id: typeof track.track_id === 'string' ? track.track_id : '',
        name: typeof track.name === 'string' && track.name !== '' ? track.name : 'Faixa',
        family: typeof track.family === 'string' ? track.family : 'unknown',
        note_count: typeof track.note_count === 'number' ? track.note_count : 0
      };
    });
    var selectedIds = valid.filter(function (v) { return v.selected; }).map(function (v) { return v.id; });
    return {
      title: initialTitle(result),
      valid: valid,
      unknownTracks: unknownTracks,
      tracks: tracks,
      selectedIds: selectedIds
    };
  }

  function isSelected(state, id) {
    return state.selectedIds.indexOf(id) >= 0;
  }

  function toggle(state, id) {
    var known = state.valid.some(function (v) { return v.id === id; });
    if (!known) return false;
    var i = state.selectedIds.indexOf(id);
    if (i >= 0) state.selectedIds.splice(i, 1);
    else state.selectedIds.push(id);
    return true;
  }

  function selectAll(state) {
    state.selectedIds = state.valid.map(function (v) { return v.id; });
  }

  function deselectAll(state) {
    state.selectedIds = [];
  }

  function counterText(state) {
    return state.selectedIds.length + ' de ' + state.valid.length + ' instrumentos selecionados';
  }

  function validateSelection(state) {
    if (!state.valid.length) {
      return { ok: false, error: 'Nenhum instrumento foi identificado com confiança suficiente. Revise a análise ou selecione uma faixa manualmente quando essa opção estiver disponível.' };
    }
    if (!state.selectedIds.length) {
      return { ok: false, error: 'Selecione pelo menos um instrumento.' };
    }
    return { ok: true, error: null };
  }

  function validateTitle(title) {
    var text = typeof title === 'string' ? title.trim() : '';
    if (text === '') return { ok: true, value: TITLE_DEFAULT };
    if (text.length > TITLE_MAX) {
      return { ok: false, error: 'Título deve ter no máximo ' + TITLE_MAX + ' caracteres.' };
    }
    return { ok: true, value: text };
  }

  function trackIdsFor(state, instrumentId) {
    var ids = [];
    state.tracks.forEach(function (track) {
      if (track && track.instrument_id === instrumentId && typeof track.track_id === 'string') {
        ids.push(track.track_id);
      }
    });
    return ids;
  }

  function buildPayload(state, jobId, title) {
    var checked = validateTitle(title);
    var selected = state.selectedIds.slice().sort();
    return {
      job_id: jobId,
      title: checked.ok ? checked.value : String(title || '').slice(0, TITLE_MAX),
      selected_instruments: selected.map(function (id) {
        return { instrument_id: id, track_ids: trackIdsFor(state, id).sort() };
      })
    };
  }

  function errorForSelect(status) {
    if (status === 401) return 'Faça login para salvar a seleção.';
    if (status === 404) return 'Análise não encontrada.';
    if (status === 400) return 'Seleção inválida.';
    if (status === 409) return 'A análise ainda não está pronta.';
    if (status === 422) return 'Instrumento ou faixa inválida.';
    if (status === 0) return 'Não foi possível conectar ao servidor.';
    return 'Não foi possível salvar a seleção. Tente novamente.';
  }

  function submitSelection(jobId, state, title, fetchImpl) {
    var fetchFn = fetchImpl || (typeof fetch !== 'undefined' ? fetch : null);
    if (!fetchFn) return Promise.reject(new Error(errorForSelect(0)));
    var check = validateSelection(state);
    if (!check.ok) return Promise.reject(new Error(check.error));
    var titleCheck = validateTitle(title);
    if (!titleCheck.ok) return Promise.reject(new Error(titleCheck.error));
    var payload = buildPayload(state, jobId, title);
    return fetchFn(SELECT_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(payload)
    }).then(function (response) {
      return response.text().then(function (text) {
        var data = null;
        try { data = JSON.parse(text); } catch (e) { data = null; }
        if (response.status === 200 && data && data.success === true) return data;
        throw new Error(errorForSelect(response.status));
      });
    }).catch(function (err) {
      if (err && (err.message === 'Failed to fetch' || err.message === 'NetworkError when attempting to fetch resource.')) {
        throw new Error(errorForSelect(0));
      }
      throw err instanceof Error ? err : new Error(errorForSelect(-1));
    });
  }

  function errorForGenerate(status) {
    if (status === 401) return 'Sua sessão expirou. Faça login novamente.';
    if (status === 404) return 'Transcrição não disponível.';
    if (status === 400) return 'Seleção inválida.';
    if (status === 409) return 'O job ainda está em processamento ou não pode ser gerado neste estado.';
    if (status === 422) return 'Não foi possível gerar com esta seleção. Revise os instrumentos e o título.';
    if (status === 0) return 'Não foi possível conectar ao servidor.';
    return 'Não foi possível gerar a partitura. Tente novamente.';
  }

  function validateForGenerate(jobId, state, title) {
    if (typeof jobId !== 'string' || jobId === '') {
      return { ok: false, error: 'Job inválido.' };
    }
    var titleCheck = validateTitle(title);
    if (!titleCheck.ok) return titleCheck;
    var check = validateSelection(state);
    if (!check.ok) return check;
    for (var i = 0; i < state.selectedIds.length; i++) {
      var ids = trackIdsFor(state, state.selectedIds[i]);
      if (!ids.length) {
        return { ok: false, error: 'Faixa inválida para este instrumento.' };
      }
    }
    return { ok: true, error: null };
  }

  function requestGenerate(jobId, state, title, fetchImpl, format) {
    var fetchFn = fetchImpl || (typeof fetch !== 'undefined' ? fetch : null);
    if (!fetchFn) return Promise.reject(new Error(errorForGenerate(0)));
    var fmt = (format === 'midi' || format === 'pdf') ? format : 'json';
    var check = validateForGenerate(jobId, state, title);
    if (!check.ok) return Promise.reject(new Error(check.error));
    var payload = buildPayload(state, jobId, title);
    return fetchFn(GENERATE_URL + '?format=' + fmt, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: fmt === 'json' ? 'application/json' : '*/*' },
      body: JSON.stringify(payload)
    }).then(function (response) {
      if (fmt === 'json') {
        return response.text().then(function (text) {
          var data = null;
          try { data = JSON.parse(text); } catch (e) { data = null; }
          if (response.status === 200 && data && data.success === true) return data;
          throw new Error(errorForGenerate(response.status));
        });
      }
      if (response.status === 200 && typeof response.blob === 'function') {
        return response.blob().then(function (blob) {
          return { blob: blob, filename: fmt === 'pdf' ? 'partitura.pdf' : 'partitura.mid' };
        });
      }
      return response.text().then(function () {
        throw new Error(errorForGenerate(response.status));
      });
    }).catch(function (err) {
      if (err && (err.message === 'Failed to fetch' || err.message === 'NetworkError when attempting to fetch resource.')) {
        throw new Error(errorForGenerate(0));
      }
      throw err instanceof Error ? err : new Error(errorForGenerate(-1));
    });
  }

  function saveDownload(blob, filename, doc) {
    var d = doc || (typeof document !== 'undefined' ? document : null);
    var creator = (typeof URL !== 'undefined' && URL.createObjectURL) ? URL : null;
    if (!d || !creator || !blob) return false;
    var url = creator.createObjectURL(blob);
    var a = d.createElement('a');
    a.href = url;
    a.download = filename;
    if (d.body && d.body.appendChild) {
      d.body.appendChild(a);
      if (typeof a.click === 'function') a.click();
      d.body.removeChild(a);
    } else if (typeof a.click === 'function') {
      a.click();
    }
    if (creator.revokeObjectURL) {
      setTimeout(function () { creator.revokeObjectURL(url); }, 4000);
    }
    return true;
  }

  /* ---------- Render DOM (somente texto seguro) ---------- */
  function renderInto(container, state, hooks) {
    hooks = hooks || {};
    clearChildren(container);
    var doc = activeDoc;

    var titleLabel = el('label', 'field__label', 'Título da partitura');
    if (titleLabel.setAttribute) titleLabel.setAttribute('for', 'audio2-sel-title');
    container.appendChild(titleLabel);
    var titleInput = doc.createElement('input');
    titleInput.className = 'field__input';
    titleInput.id = 'audio2-sel-title';
    titleInput.type = 'text';
    titleInput.maxLength = TITLE_MAX;
    titleInput.value = state.title;
    titleInput.addEventListener('change', function () {
      var check = validateTitle(titleInput.value);
      state.title = check.ok ? check.value : titleInput.value;
      if (typeof hooks.onTitle === 'function') hooks.onTitle(state.title, check);
    });
    container.appendChild(titleInput);

    container.appendChild(el('h4', 'audio2__subtitle', 'Instrumentos detectados'));

    var controls = el('div', 'audio2__actions');
    var selectAllBtn = el('button', 'btn btn--ghost btn--sm', 'Selecionar todos');
    selectAllBtn.type = 'button';
    selectAllBtn.addEventListener('click', function () {
      selectAll(state);
      refresh();
      if (typeof hooks.onChange === 'function') hooks.onChange(state);
    });
    var deselectBtn = el('button', 'btn btn--ghost btn--sm', 'Desmarcar todos');
    deselectBtn.type = 'button';
    deselectBtn.addEventListener('click', function () {
      deselectAll(state);
      refresh();
      if (typeof hooks.onChange === 'function') hooks.onChange(state);
    });
    controls.appendChild(selectAllBtn);
    controls.appendChild(deselectBtn);
    var counter = el('p', 'audio2__counter', counterText(state));
    counter.setAttribute('role', 'status');
    counter.setAttribute('aria-live', 'polite');
    controls.appendChild(counter);
    container.appendChild(controls);

    var list = el('div', 'audio2__cards');
    container.appendChild(list);
    var errorBox = el('p', 'gen-feedback', '');
    errorBox.setAttribute('role', 'alert');
    setVisible(errorBox, false);
    container.appendChild(errorBox);

    function cardId(kind, id) {
      return 'audio2-sel-' + kind + '-' + String(id).replace(/[^a-zA-Z0-9_-]/g, '_');
    }

    function renderCards() {
      clearChildren(list);
      if (!state.valid.length && !state.unknownTracks.length) {
        list.appendChild(el('p', null, 'Nenhum instrumento detectado nesta análise.'));
      }
      state.valid.forEach(function (inst) {
        var card = el('div', 'audio2__card');
        var box = doc.createElement('input');
        box.type = 'checkbox';
        box.id = cardId('inst', inst.id);
        box.checked = isSelected(state, inst.id);
        var label = el('label', 'audio2__card-label', '');
        label.setAttribute('for', box.id);
        label.appendChild(el('strong', null, inst.name));
        var conf = confidencePercent(inst.confidence);
        var desc = (inst.family !== 'unknown' ? inst.family : 'Família não identificada') +
          (conf !== null ? ' · Confiança: ' + conf : '') + ' · Detectado';
        var described = el('span', 'audio2__card-desc', desc);
        var descId = cardId('desc', inst.id);
        described.id = descId;
        box.setAttribute('aria-describedby', descId);
        (function (id) {
          box.addEventListener('change', function () {
            toggle(state, id);
            box.checked = isSelected(state, id);
            counter.textContent = counterText(state);
            setVisible(errorBox, false);
            if (typeof hooks.onChange === 'function') hooks.onChange(state);
          });
        })(inst.id);
        card.appendChild(box);
        var wrap = el('div', null, '');
        wrap.appendChild(label);
        wrap.appendChild(described);
        var trackRows = state.tracks.filter(function (t) { return t && t.instrument_id === inst.id; });
        trackRows.forEach(function (t) {
          var count = (typeof t.note_count === 'number') ? t.note_count : 0;
          wrap.appendChild(el('p', 'audio2__track',
            safeName(t) + ' · ' + count + (count === 1 ? ' nota' : ' notas')));
        });
        card.appendChild(wrap);
        list.appendChild(card);
      });
      state.unknownTracks.forEach(function (track, index) {
        var card = el('div', 'audio2__card audio2__card--unknown');
        var box = doc.createElement('input');
        box.type = 'checkbox';
        box.id = cardId('unknown', index);
        box.checked = false;
        box.disabled = true;
        var label = el('label', 'audio2__card-label', '');
        label.setAttribute('for', box.id);
        label.appendChild(el('strong', null, 'Instrumento não identificado'));
        var desc = el('span', 'audio2__card-desc',
          'Desconhecido · Sem confiança suficiente · ' + track.note_count +
          (track.note_count === 1 ? ' nota' : ' notas'));
        label.appendChild(desc);
        card.appendChild(box);
        card.appendChild(label);
        list.appendChild(card);
      });
    }

    function safeName(t) {
      return (typeof t.name === 'string' && t.name !== '') ? t.name : 'Faixa';
    }

    function refresh() {
      renderCards();
      counter.textContent = counterText(state);
    }

    var submitBtn = el('button', 'btn btn--primary', 'Salvar seleção');
    submitBtn.type = 'button';
    submitBtn.addEventListener('click', function () {
      setVisible(errorBox, false);
      var check = validateSelection(state);
      var titleCheck = validateTitle(titleInput.value);
      if (!titleCheck.ok) {
        errorBox.textContent = titleCheck.error;
        setVisible(errorBox, true);
        titleInput.focus();
        return;
      }
      state.title = titleCheck.value;
      if (!check.ok) {
        errorBox.textContent = check.error;
        setVisible(errorBox, true);
        return;
      }
      submitBtn.disabled = true;
      var done = function () { submitBtn.disabled = false; };
      Promise.resolve()
        .then(function () { return hooks.onSubmit(state, state.title); })
        .then(function (response) {
          done();
          errorBox.textContent = '';
          setVisible(errorBox, false);
          if (typeof hooks.onSaved === 'function') hooks.onSaved(response);
        })
        .catch(function (err) {
          done();
          errorBox.textContent = (err && err.message) || 'Não foi possível salvar a seleção. Tente novamente.';
          setVisible(errorBox, true);
        });
    });
    container.appendChild(submitBtn);

    var generateBox = el('div', 'audio2__generate');
    var generateBtn = el('button', 'btn btn--primary', 'Gerar partitura');
    generateBtn.type = 'button';
    var generateStatus = el('p', 'gen-feedback', '');
    generateStatus.setAttribute('role', 'status');
    generateStatus.setAttribute('aria-live', 'polite');
    setVisible(generateStatus, false);
    var downloadsBox = el('div', 'audio2__actions');
    setVisible(downloadsBox, false);
    var pdfBtn = el('button', 'btn btn--dark-outline', 'Baixar PDF');
    pdfBtn.type = 'button';
    var midiBtn = el('button', 'btn btn--dark-outline', 'Baixar MIDI');
    midiBtn.type = 'button';
    downloadsBox.appendChild(pdfBtn);
    downloadsBox.appendChild(midiBtn);
    generateBox.appendChild(generateBtn);
    generateBox.appendChild(generateStatus);
    generateBox.appendChild(downloadsBox);
    container.appendChild(generateBox);

    var generating = false;
    function setGenerating(busy, label) {
      generating = busy;
      generateBtn.disabled = busy;
      if (busy) {
        generateStatus.textContent = label || 'Gerando partitura...';
        setVisible(generateStatus, true);
      }
    }

    function showGenerateError(message) {
      generateStatus.textContent = message;
      setVisible(generateStatus, true);
    }

    generateBtn.addEventListener('click', function () {
      if (generating) return;
      setVisible(downloadsBox, false);
      var titleCheck = validateTitle(titleInput.value);
      if (!titleCheck.ok) {
        showGenerateError(titleCheck.error);
        titleInput.focus();
        return;
      }
      state.title = titleCheck.value;
      var check = validateForGenerate(mountedJobId(), state, state.title);
      if (!check.ok) {
        showGenerateError(check.error);
        return;
      }
      setGenerating(true);
      var done = function () { setGenerating(false); };
      var requester = (typeof hooks.onGenerate === 'function')
        ? function () { return hooks.onGenerate(state, state.title, 'json'); }
        : function () { return requestGenerate(mountedJobId(), state, state.title, undefined, 'json'); };
      Promise.resolve()
        .then(requester)
        .then(function () {
          done();
          generateStatus.textContent = 'Partitura gerada com sucesso';
          setVisible(generateStatus, true);
          setVisible(downloadsBox, true);
          if (typeof hooks.onGenerated === 'function') hooks.onGenerated(state);
        })
        .catch(function (err) {
          done();
          showGenerateError((err && err.message) || 'Não foi possível gerar a partitura. Tente novamente.');
        });
    });

    function downloadFormat(fmt, btn) {
      if (generating) return;
      setGenerating(true, fmt === 'pdf' ? 'Gerando PDF...' : 'Gerando MIDI...');
      btn.disabled = true;
      var fin = function () {
        btn.disabled = false;
        setGenerating(false);
        setVisible(generateStatus, false);
      };
      var requester = (typeof hooks.onDownload === 'function')
        ? function () { return hooks.onDownload(state, state.title, fmt); }
        : function () {
          return requestGenerate(mountedJobId(), state, state.title, undefined, fmt)
            .then(function (res) {
              saveDownload(res.blob, res.filename);
              return res;
            });
        };
      Promise.resolve()
        .then(requester)
        .then(function () { fin(); })
        .catch(function (err) {
          fin();
          showGenerateError((err && err.message) || 'Não foi possível baixar o arquivo. Tente novamente.');
        });
    }

    pdfBtn.addEventListener('click', function () { downloadFormat('pdf', pdfBtn); });
    midiBtn.addEventListener('click', function () { downloadFormat('midi', midiBtn); });

    function mountedJobId() {
      return (typeof hooks.jobId === 'string' && hooks.jobId !== '') ? hooks.jobId : '';
    }

    renderCards();
    return {
      refresh: refresh,
      errorBox: errorBox,
      counter: counter,
      titleInput: titleInput,
      generateBtn: generateBtn,
      generateStatus: generateStatus,
      downloadsBox: downloadsBox
    };
  }

  function mount(container, result, jobId, hooks) {
    activeDoc = (container && container.ownerDocument) ||
      (typeof document !== 'undefined' ? document : null);
    if (!activeDoc) return null;
    var state = createSelectionState(result);
    var merged = {};
    Object.keys(hooks || {}).forEach(function (k) { merged[k] = hooks[k]; });
    merged.jobId = jobId;
    var ui = renderInto(container, state, merged);
    return { state: state, ui: ui, jobId: jobId };
  }

  return {
    TITLE_MAX: TITLE_MAX,
    TITLE_DEFAULT: TITLE_DEFAULT,
    SELECT_URL: SELECT_URL,
    GENERATE_URL: GENERATE_URL,
    GENERATE_FORMATS: GENERATE_FORMATS,
    createSelectionState: createSelectionState,
    isSelected: isSelected,
    toggle: toggle,
    selectAll: selectAll,
    deselectAll: deselectAll,
    counterText: counterText,
    validateSelection: validateSelection,
    validateTitle: validateTitle,
    trackIdsFor: trackIdsFor,
    buildPayload: buildPayload,
    errorForSelect: errorForSelect,
    submitSelection: submitSelection,
    errorForGenerate: errorForGenerate,
    validateForGenerate: validateForGenerate,
    requestGenerate: requestGenerate,
    saveDownload: saveDownload,
    renderInto: renderInto,
    mount: mount
  };
}));
