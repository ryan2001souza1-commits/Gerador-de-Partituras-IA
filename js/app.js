/* ============================================================
   Gerador de Partituras IA — Landing page (etapa 1) + tela de
   geração (etapa 2). JavaScript puro (ES6+), modular por
   responsabilidades. Escopo: SOMENTE interface (sem API/backend).
   ============================================================ */

(function () {
  'use strict';

  var THEME_KEY = 'gpi-theme';

  /* ---------- Módulo: Tema claro/escuro ---------- */
  var ThemeModule = {
    root: document.documentElement,
    toggleButton: null,
    icon: null,

    getPreferred: function () {
      try {
        var saved = window.localStorage.getItem(THEME_KEY);
        if (saved === 'light' || saved === 'dark') return saved;
      } catch (e) {
        /* localStorage indisponível: segue para preferência do SO */
      }
      if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        return 'dark';
      }
      return 'light';
    },

    apply: function (theme) {
      this.root.setAttribute('data-theme', theme);
      var meta = document.querySelector('meta[name="theme-color"]');
      if (meta) meta.setAttribute('content', theme === 'dark' ? '#0f0c1d' : '#ffffff');
      if (this.toggleButton) {
        var isDark = theme === 'dark';
        this.toggleButton.setAttribute('aria-pressed', String(isDark));
        this.toggleButton.setAttribute(
          'aria-label',
          isDark ? 'Alternar para tema claro' : 'Alternar para tema escuro'
        );
      }
      if (this.icon) this.icon.textContent = theme === 'dark' ? '☀️' : '🌙';
    },

    save: function (theme) {
      try {
        window.localStorage.setItem(THEME_KEY, theme);
      } catch (e) {
        /* ignora: preferência só não persiste */
      }
    },

    toggle: function () {
      var next = this.root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      this.apply(next);
      this.save(next);
    },

    init: function () {
      this.toggleButton = document.getElementById('theme-toggle');
      this.icon = document.getElementById('theme-icon');
      this.apply(this.getPreferred());
      if (this.toggleButton) {
        this.toggleButton.addEventListener('click', this.toggle.bind(this));
      }
    }
  };

  /* ---------- Módulo: Menu mobile ---------- */
  var MenuModule = {
    toggleButton: null,
    menu: null,

    isOpen: function () {
      return this.toggleButton && this.toggleButton.getAttribute('aria-expanded') === 'true';
    },

    open: function () {
      this.menu.hidden = false;
      this.toggleButton.setAttribute('aria-expanded', 'true');
      this.toggleButton.setAttribute('aria-label', 'Fechar menu');
    },

    close: function () {
      this.menu.hidden = true;
      this.toggleButton.setAttribute('aria-expanded', 'false');
      this.toggleButton.setAttribute('aria-label', 'Abrir menu');
    },

    init: function () {
      this.toggleButton = document.getElementById('menu-toggle');
      this.menu = document.getElementById('nav-mobile');
      if (!this.toggleButton || !this.menu) return;

      this.toggleButton.addEventListener('click', function () {
        if (this.isOpen()) this.close();
        else this.open();
      }.bind(this));

      // Fecha ao clicar em qualquer link do menu móvel
      this.menu.addEventListener('click', function (event) {
        if (event.target.closest('a')) this.close();
      }.bind(this));

      // Fecha com Escape e devolve o foco ao botão
      document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && this.isOpen()) {
          this.close();
          this.toggleButton.focus();
        }
      }.bind(this));

      // Se redimensionar para desktop, garante menu fechado
      window.addEventListener('resize', function () {
        if (window.innerWidth >= 960 && this.isOpen()) this.close();
      }.bind(this));
    }
  };

  /* ---------- Módulo: Demonstração (sem backend) ---------- */
  var DemoModule = {
    init: function () {
      var button = document.getElementById('demo-generate');
      var feedback = document.getElementById('demo-feedback');
      if (!button || !feedback) return;

      button.addEventListener('click', function () {
        feedback.hidden = false;
        feedback.textContent =
          'Demonstração: o gerador de partituras será implementado em uma próxima etapa. ' +
          'Por enquanto, nenhum áudio ou partitura foi gerado e nada foi enviado para servidores.';
      });
    }
  };

  /* ---------- Módulo: Gerador (etapa 3 — via backend PHP/Python) -----
     Fluxo: Frontend --POST JSON--> /api/generate.php --stdin/stdout-->
     python/generator.py. Sem IA real: o Python devolve resposta simulada.
     A função generateScore(params) concentra a chamada; mantém a mesma
     assinatura generateScore(params) -> Promise<result>. Nenhuma chave,
     credencial ou acesso a banco é usado aqui. */
  var GeneratorModule = {
    HISTORY_KEY: 'gpi-historico',
    HISTORY_MAX: 5,
    DESCRIPTION_MAX: 2000,
    API_ENDPOINT: '/api/generate.php',

    form: null,
    description: null,
    counter: null,
    generateButton: null,
    feedback: null,
    resultEmpty: null,
    resultSim: null,
    resultNotes: null,
    resultMeta: null,
    historyList: null,
    historyEmpty: null,
    historyClear: null,
    isGenerating: false,

    getCheckedValue: function (name) {
      var checked = this.form.querySelector('input[name="' + name + '"]:checked');
      return checked ? checked.value : '';
    },

    getParams: function () {
      return {
        descricao: this.description.value.trim(),
        instrumento: this.getCheckedValue('instrumento'),
        tom: document.getElementById('tom').value,
        andamento: document.getElementById('andamento').value,
        compasso: this.getCheckedValue('compasso'),
        dificuldade: this.getCheckedValue('dificuldade'),
        estilo: this.getCheckedValue('estilo')
      };
    },

    updateCounter: function () {
      var len = this.description.value.length;
      this.counter.textContent = len + ' / ' + this.DESCRIPTION_MAX;
    },

    showFeedback: function (message, kind) {
      this.feedback.hidden = false;
      this.feedback.textContent = message;
      this.feedback.classList.toggle('gen-feedback--error', kind === 'error');
      this.feedback.classList.toggle('gen-feedback--success', kind === 'success');
    },

    hideFeedback: function () {
      this.feedback.hidden = true;
      this.feedback.textContent = '';
    },

    STAGE_MESSAGES: ['Gerando com IA…', 'Validando partitura…', 'Salvando…'],

    setLoading: function (loading) {
      this.isGenerating = loading;
      this.generateButton.disabled = loading;
      this.generateButton.setAttribute('aria-busy', String(loading));
      this.generateButton.classList.toggle('btn--loading', loading);
      this.generateButton.innerHTML = loading
        ? '<span class="spinner" aria-hidden="true"></span> Gerando…'
        : '<span aria-hidden="true">✦</span> Gerar Partitura com IA <span aria-hidden="true">›</span>';
      if (this.stageTimer) {
        window.clearInterval(this.stageTimer);
        this.stageTimer = null;
      }
      if (loading) {
        var i = 0;
        var self = this;
        this.showFeedback(this.STAGE_MESSAGES[0], 'success');
        this.stageTimer = window.setInterval(function () {
          i = Math.min(i + 1, self.STAGE_MESSAGES.length - 1);
          self.showFeedback(self.STAGE_MESSAGES[i], 'success');
        }, 4000);
      }
    },

    /* Chamada ao backend. Validação básica no frontend; o PHP revalida
       tudo no servidor. Rejeita a Promise com Error(mensagem) em falhas. */
    generateScore: function (params) {
      var payload = {
        descricao: params.descricao,
        instrumento: params.instrumento,
        tom: params.tom,
        andamento: params.andamento,
        compasso: params.compasso,
        dificuldade: params.dificuldade,
        estilo: params.estilo
      };
      if (!payload.descricao) {
        return Promise.reject(new Error('EMPTY'));
      }
      if (payload.descricao.length > this.DESCRIPTION_MAX) {
        return Promise.reject(new Error('TOO_LONG'));
      }
      if (typeof window.fetch !== 'function') {
        return Promise.reject(new Error('Navegador sem suporte a fetch.'));
      }
      return window.fetch(this.API_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(payload)
      }).then(function (response) {
        return response.text().then(function (text) {
          var data = null;
          try {
            data = JSON.parse(text);
          } catch (e) {
            data = null;
          }
          if (!response.ok || !data || data.success !== true || !data.score) {
            var serverMessage = data && typeof data.error === 'string' ? data.error : '';
            throw new Error(serverMessage || ('Erro ao gerar partitura (HTTP ' + response.status + ').'));
          }
          var score = data.score;
          var labels = (score && typeof score.labels === 'object' && score.labels !== null)
            ? score.labels
            : { instrumento: params.instrumento, tom: params.tom, andamento: params.andamento, compasso: params.compasso, estilo: params.estilo };
          return {
            params: params,
            labels: labels,
            title: (score && typeof score.title === 'string') ? score.title : '',
            tempo: (score && typeof score.tempo === 'number') ? score.tempo : null,
            timeSignature: (score && typeof score.time_signature === 'string') ? score.time_signature : params.compasso,
            notes: (score && Array.isArray(score.notes) && score.notes.length) ? score.notes : [],
            createdAt: new Date().toISOString(),
            message: typeof data.message === 'string' ? data.message : '',
            scoreId: typeof data.score_id === 'string' && data.score_id !== '' ? data.score_id : null
          };
        });
      });
    },

    GLYPHS: { whole: '○', half: '◐', quarter: '♩', eighth: '♪', sixteenth: '♬' },
    DURATIONS_PT: { whole: 'semibreve', half: 'mínima', quarter: 'semínima', eighth: 'colcheia', sixteenth: 'semicolcheia' },

    noteDisplay: function (note, index) {
      if (typeof note === 'string') return { glyph: note, label: note }; // legado
      var dur = note.duration || 'quarter';
      var durPt = this.DURATIONS_PT[dur] || dur;
      if (note.rest) return { glyph: '·', label: 'Pausa (' + durPt + ')' };
      return { glyph: this.GLYPHS[dur] || '♩', label: (note.pitch || '?') + (note.octave == null ? '' : note.octave) + ' (' + durPt + ')' };
    },

    renderResult: function (result) {
      var labels = result.labels || result.params || {};
      var notes = Array.isArray(result.notes) ? result.notes : [];
      this.current = {
        notes: notes,
        tempo: (typeof result.tempo === 'number') ? result.tempo : null,
        title: result.title || '',
        labels: labels,
        timeSignature: result.timeSignature || ''
      };
      if (typeof PlayerModule !== 'undefined') PlayerModule.reset();
      if (this.resultSong) this.resultSong.textContent = result.title || 'Partitura gerada';
      this.resultNotes.innerHTML = '';
      notes.slice(0, 5).forEach(function (note, i) {
        var span = document.createElement('span');
        span.className = 'note note--' + ((i % 5) + 1);
        span.textContent = this.noteDisplay(note, i).glyph;
        span.style.animationDelay = (i * 0.3) + 's';
        this.resultNotes.appendChild(span);
      }, this);
      this.resultMeta.innerHTML = '';
      var chips = [labels.instrumento, labels.tom, [labels.andamento, labels.compasso].filter(Boolean).join(' · '), labels.estilo]
        .filter(function (c) { return !!c; });
      if (typeof result.tempo === 'number') chips.push('♩ = ' + result.tempo);
      chips.forEach(function (label) {
        var chip = document.createElement('span');
        chip.className = 'chip';
        chip.textContent = label;
        this.resultMeta.appendChild(chip);
      }, this);
      if (this.resultList) {
        this.resultList.innerHTML = '';
        notes.forEach(function (note, i) {
          var li = document.createElement('li');
          li.textContent = (i + 1) + '. ' + this.noteDisplay(note, i).label;
          this.resultList.appendChild(li);
        }, this);
      }
      this.resultEmpty.hidden = true;
      this.resultSim.hidden = false;
    },

    readHistory: function () {
      try {
        var raw = window.localStorage.getItem(this.HISTORY_KEY);
        if (!raw) return [];
        var parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
      } catch (e) {
        return [];
      }
    },

    writeHistory: function (items) {
      try {
        window.localStorage.setItem(this.HISTORY_KEY, JSON.stringify(items));
      } catch (e) {
        /* ignora: histórico só não persiste */
      }
    },

    saveToHistory: function (result) {
      var items = this.readHistory();
      items.unshift({
        id: 'gpi-' + Date.now().toString(36),
        descricao: result.params.descricao,
        instrumento: result.params.instrumento,
        tom: result.params.tom,
        andamento: result.params.andamento,
        compasso: result.params.compasso,
        dificuldade: result.params.dificuldade,
        estilo: result.params.estilo,
        data: result.createdAt
      });
      this.writeHistory(items.slice(0, this.HISTORY_MAX));
      this.renderHistory();
    },

    formatDate: function (iso) {
      try {
        return new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
      } catch (e) {
        return iso;
      }
    },

    truncate: function (text, max) {
      if (text.length <= max) return text;
      return text.slice(0, max - 1).trim() + '…';
    },

    renderHistory: function () {
      var items = this.readHistory();
      this.historyList.innerHTML = '';
      this.historyEmpty.hidden = items.length > 0;
      this.historyClear.hidden = items.length === 0;
      items.forEach(function (item) {
        var li = document.createElement('li');
        li.className = 'history__item';

        var desc = document.createElement('p');
        desc.className = 'history__desc';
        desc.textContent = this.truncate(item.descricao, 90);
        desc.title = item.descricao;
        li.appendChild(desc);

        var meta = document.createElement('p');
        meta.className = 'history__meta';
        meta.textContent = item.instrumento + ' · ' + item.tom + ' · ' + item.andamento + ' · ' + this.formatDate(item.data);
        li.appendChild(meta);

        var actions = document.createElement('div');
        actions.className = 'history__actions';

        var load = document.createElement('button');
        load.type = 'button';
        load.className = 'link-btn';
        load.textContent = 'Carregar';
        load.setAttribute('data-load', item.id);
        load.setAttribute('aria-label', 'Carregar partitura: ' + this.truncate(item.descricao, 50));
        actions.appendChild(load);

        var del = document.createElement('button');
        del.type = 'button';
        del.className = 'link-btn link-btn--danger';
        del.textContent = 'Excluir';
        del.setAttribute('data-del', item.id);
        del.setAttribute('aria-label', 'Excluir partitura: ' + this.truncate(item.descricao, 50));
        actions.appendChild(del);

        li.appendChild(actions);
        this.historyList.appendChild(li);
      }, this);
    },

    setRadio: function (name, value) {
      var input = this.form.querySelector('input[name="' + name + '"][value="' + value + '"]');
      if (input) input.checked = true;
    },

    loadIntoForm: function (item) {
      this.description.value = item.descricao;
      this.updateCounter();
      this.setRadio('instrumento', item.instrumento);
      document.getElementById('tom').value = item.tom;
      document.getElementById('andamento').value = item.andamento;
      this.setRadio('compasso', item.compasso);
      this.setRadio('dificuldade', item.dificuldade);
      this.setRadio('estilo', item.estilo);
      this.showFeedback('Partitura recente carregada no formulário. Clique em “Gerar partitura” para simular novamente.', 'success');
      document.getElementById('criar').scrollIntoView({ behavior: 'smooth', block: 'start' });
      this.description.focus({ preventScroll: true });
    },

    handleSubmit: function (event) {
      event.preventDefault();
      if (this.isGenerating) return;
      var params = this.getParams();
      if (!params.descricao) {
        this.description.setAttribute('aria-invalid', 'true');
        this.showFeedback('Descreva sua música antes de gerar. Por exemplo: “Crie uma música para piano, estilo romântico, em Dó maior, com andamento moderado…”.', 'error');
        this.description.focus();
        return;
      }
      this.description.removeAttribute('aria-invalid');
      this.hideFeedback();
      this.setLoading(true);
      this.generateScore(params).then(function (result) {
        this.setLoading(false);
        this.renderResult(result);
        this.saveToHistory(result);
        this.showFeedback('Partitura pronta. ' + (result.message || ''), 'success');
        this.lastScoreId = result.scoreId || null;
        if (result.scoreId && typeof ScoresModule !== 'undefined') ScoresModule.refresh();
      }.bind(this)).catch(function (err) {
        this.setLoading(false);
        var code = err && err.message ? err.message : '';
        if (code === 'EMPTY') {
          this.showFeedback('Descreva sua música antes de gerar.', 'error');
        } else if (code === 'TOO_LONG') {
          this.showFeedback('Descrição deve ter no máximo 2000 caracteres.', 'error');
        } else if (code === 'Failed to fetch' || code === 'NetworkError when attempting to fetch resource.') {
          this.showFeedback('Não foi possível alcançar o backend. Sirva o projeto via PHP (ex.: php -S localhost:8000) e tente novamente.', 'error');
        } else {
          this.showFeedback(code || 'Erro ao gerar partitura. Tente novamente.', 'error');
        }
      }.bind(this));
    },

    init: function () {
      this.form = document.getElementById('generator-form');
      if (!this.form) return;
      this.description = document.getElementById('descricao');
      this.counter = document.getElementById('contador');
      this.generateButton = document.getElementById('gerar-btn');
      this.feedback = document.getElementById('gen-feedback');
      this.resultEmpty = document.getElementById('resultado-vazio');
      this.resultSim = document.getElementById('resultado-sim');
      this.resultNotes = document.getElementById('resultado-notas');
      this.resultMeta = document.getElementById('resultado-meta');
      this.resultSong = document.getElementById('resultado-musica');
      this.resultList = document.getElementById('resultado-lista');
      this.historyList = document.getElementById('historico-lista');
      this.historyEmpty = document.getElementById('historico-vazio');
      this.historyClear = document.getElementById('historico-limpar');

      this.updateCounter();
      this.renderHistory();

      this.description.addEventListener('input', this.updateCounter.bind(this));
      this.form.addEventListener('submit', this.handleSubmit.bind(this));

      this.historyList.addEventListener('click', function (event) {
        var loadBtn = event.target.closest('[data-load]');
        var delBtn = event.target.closest('[data-del]');
        var items = this.readHistory();
        if (loadBtn) {
          var found = items.filter(function (i) { return i.id === loadBtn.getAttribute('data-load'); })[0];
          if (found) this.loadIntoForm(found);
          return;
        }
        if (delBtn) {
          var id = delBtn.getAttribute('data-del');
          this.writeHistory(items.filter(function (i) { return i.id !== id; }));
          this.renderHistory();
        }
      }.bind(this));

      this.historyClear.addEventListener('click', function () {
        this.writeHistory([]);
        this.renderHistory();
      }.bind(this));

      /* Botões demonstrativos do resultado (etapas futuras). */
      document.addEventListener('click', function (event) {
        var btn = event.target.closest('[data-future]');
        if (!btn || !this.resultSim || this.resultSim.hidden) return;
        var labels = { editar: 'edição' };
        var kind = btn.getAttribute('data-future');
        this.showFeedback('A ' + (labels[kind] || 'funcionalidade') + ' será implementada em uma próxima etapa. Por enquanto, este botão é apenas demonstrativo.', 'success');
      }.bind(this));
    }
  };

  /* ---------- Módulo: Player (Web Audio API, sem dependências) -----
     Reproduz result.notes reais (pitch/octave/duration/rest) com o BPM
     da partitura. Sem autoplay: o AudioContext nasce no clique.
     Estados: idle | playing | paused. Uma reprodução por vez. */
  var PlayerModule = {
    SEMITONES: { 'C': 0, 'C#': 1, 'D': 2, 'D#': 3, 'E': 4, 'F': 5, 'F#': 6, 'G': 7, 'G#': 8, 'A': 9, 'A#': 10, 'B': 11 },
    BEATS: { whole: 4, half: 2, quarter: 1, eighth: 0.5, sixteenth: 0.25 },
    DEFAULT_BPM: 96,

    state: 'idle', // idle | playing | paused
    ctx: null,
    master: null,
    timers: [],
    startedAt: 0, // ctx.currentTime do início (menos pausas acumuladas)
    pausedAt: 0,
    timeline: [],

    noteToFreq: function (pitch, octave) {
      if (!Object.prototype.hasOwnProperty.call(this.SEMITONES, pitch)) return null;
      if (typeof octave !== 'number' || octave < 0 || octave > 8) return null;
      var midi = (octave + 1) * 12 + this.SEMITONES[pitch];
      return 440 * Math.pow(2, (midi - 69) / 12);
    },

    /* Linha do tempo pura (testável): [{index, freq|null, start, dur}]. */
    buildTimeline: function (notes, bpm) {
      var beat = 60 / bpm;
      var t = 0;
      var out = [];
      for (var i = 0; i < notes.length; i++) {
        var n = notes[i] || {};
        var beats = this.BEATS[n.duration] || 1;
        var dur = beats * beat;
        var freq = (!n.rest) ? this.noteToFreq(n.pitch, n.octave) : null;
        out.push({ index: i, freq: freq, start: t, dur: dur, rest: !!n.rest || freq === null });
        t += dur;
      }
      return { events: out, total: t };
    },

    setButtons: function () {
      var playing = this.state === 'playing';
      var paused = this.state === 'paused';
      var active = playing || paused;
      var play = document.getElementById('play-btn');
      var pause = document.getElementById('pause-btn');
      var stop = document.getElementById('stop-btn');
      if (play) play.disabled = playing;
      if (pause) pause.disabled = !playing;
      if (stop) stop.disabled = !active;
    },

    setStatus: function (text) {
      var el = document.getElementById('playback-status');
      if (!el) return;
      el.hidden = !text;
      el.textContent = text || '';
    },

    highlight: function (index) {
      var list = document.getElementById('resultado-lista');
      if (!list) return;
      var items = list.children;
      for (var i = 0; i < items.length; i++) {
        if (items[i].classList) items[i].classList.toggle('is-active', i === index);
      }
      var current = items[index];
      if (current && current.scrollIntoView) {
        try { current.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } catch (e) { /* sem rolagem */ }
      }
    },

    clearTimers: function () {
      this.timers.forEach(function (id) { window.clearTimeout(id); });
      this.timers = [];
    },

    currentNotes: function () {
      var cur = (typeof GeneratorModule !== 'undefined') ? GeneratorModule.current : null;
      if (!cur || !Array.isArray(cur.notes) || !cur.notes.length) return null;
      for (var i = 0; i < cur.notes.length; i++) {
        if (typeof cur.notes[i] !== 'object' || cur.notes[i] === null) return 'legacy';
      }
      return cur;
    },

    play: function () {
      if (this.state === 'playing') return; // impede simultâneas
      if (this.state === 'paused') { this.resume(); return; }
      var cur = this.currentNotes();
      if (cur === null) {
        GeneratorModule.showFeedback('Gere uma partitura antes de reproduzir.', 'error');
        return;
      }
      if (cur === 'legacy') {
        GeneratorModule.showFeedback('Esta partitura salva não possui dados de altura para reprodução.', 'error');
        return;
      }
      var AC = window.AudioContext || window.webkitAudioContext;
      if (typeof AC !== 'function') {
        GeneratorModule.showFeedback('Este navegador não suporta reprodução de áudio.', 'error');
        return;
      }
      var bpm = (typeof cur.tempo === 'number' && cur.tempo >= 20 && cur.tempo <= 300) ? cur.tempo : this.DEFAULT_BPM;
      var built = this.buildTimeline(cur.notes, bpm);
      if (!built.events.length) {
        GeneratorModule.showFeedback('Partitura sem notas para reproduzir.', 'error');
        return;
      }
      this.timeline = built.events;
      try {
        this.ctx = new AC();
      } catch (e) {
        GeneratorModule.showFeedback('Não foi possível iniciar o áudio.', 'error');
        return;
      }
      var self = this;
      var scheduleAll = function () {
        self.master = self.ctx.createGain();
        self.master.gain.value = 0.9;
        self.master.connect(self.ctx.destination);
        self.startedAt = self.ctx.currentTime + 0.06;
        self.timeline.forEach(function (ev) {
          if (ev.freq !== null) self.scheduleTone(ev, self.startedAt);
          self.timers.push(window.setTimeout(function () { self.highlight(ev.index); }, Math.max(0, (self.startedAt - self.ctx.currentTime + ev.start) * 1000)));
        });
        self.timers.push(window.setTimeout(function () { self.finish(); }, Math.max(0, (self.startedAt - self.ctx.currentTime + built.total) * 1000 + 150)));
        self.state = 'playing';
        self.setButtons();
        self.setStatus('Reproduzindo…');
      };
      if (this.ctx.state === 'suspended') {
        this.ctx.resume().then(scheduleAll, function () {
          GeneratorModule.showFeedback('Não foi possível iniciar o áudio.', 'error');
        });
      } else {
        scheduleAll();
      }
    },

    scheduleTone: function (ev, base) {
      var t0 = base + ev.start;
      var osc = this.ctx.createOscillator();
      var gain = this.ctx.createGain();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(ev.freq, t0);
      gain.gain.setValueAtTime(0.0001, t0);
      gain.gain.exponentialRampToValueAtTime(0.5, t0 + 0.015);
      gain.gain.setValueAtTime(0.5, Math.max(t0 + 0.015, t0 + ev.dur - 0.04));
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + ev.dur + 0.03);
      osc.connect(gain);
      gain.connect(this.master);
      osc.start(t0);
      osc.stop(t0 + ev.dur + 0.05);
    },

    pause: function () {
      if (this.state !== 'playing' || !this.ctx) return;
      var self = this;
      this.pausedAt = this.ctx.currentTime;
      this.ctx.suspend().then(function () {
        self.clearTimers();
        self.state = 'paused';
        self.setButtons();
        self.setStatus('Pausado.');
      });
    },

    resume: function () {
      if (this.state !== 'paused' || !this.ctx) return;
      var self = this;
      var elapsed = this.pausedAt - this.startedAt;
      this.ctx.resume().then(function () {
        var sounding = false;
        self.timeline.forEach(function (ev) {
          if (ev.start + ev.dur <= elapsed) return;
          sounding = true;
          if (ev.start <= elapsed) self.highlight(ev.index);
          self.timers.push(window.setTimeout(function () { self.highlight(ev.index); },
            Math.max(0, (ev.start - elapsed) * 1000)));
        });
        var last = self.timeline.length ? self.timeline[self.timeline.length - 1] : null;
        var remaining = last ? Math.max(0, (last.start + last.dur - elapsed) * 1000) + 150 : 0;
        self.timers.push(window.setTimeout(function () { self.finish(); }, remaining));
        self.startedAt = self.ctx.currentTime - elapsed;
        self.state = 'playing';
        self.setButtons();
        self.setStatus('Reproduzindo…');
        if (!sounding) self.finish();
      });
    },

    stop: function () {
      if (this.state === 'idle') return;
      this.clearTimers();
      this.highlight(-1);
      var ctx = this.ctx;
      this.ctx = null;
      this.master = null;
      this.timeline = [];
      this.state = 'idle';
      this.setButtons();
      this.setStatus('');
      if (ctx && typeof ctx.close === 'function') {
        try { ctx.close(); } catch (e) { /* ignora */ }
      }
    },

    finish: function () {
      this.clearTimers();
      this.highlight(-1);
      var ctx = this.ctx;
      this.ctx = null;
      this.master = null;
      this.timeline = [];
      this.state = 'idle';
      this.setButtons();
      this.setStatus('');
      if (ctx && typeof ctx.close === 'function') {
        try { ctx.close(); } catch (e) { /* ignora */ }
      }
    },

    reset: function () {
      this.stop();
    },

    init: function () {
      var play = document.getElementById('play-btn');
      if (!play) return;
      var self = this;
      play.addEventListener('click', function () { self.play(); });
      document.getElementById('pause-btn').addEventListener('click', function () { self.pause(); });
      document.getElementById('stop-btn').addEventListener('click', function () { self.stop(); });
      this.setButtons();
    }
  };

  /* ---------- Módulo: MIDI (download da partitura atual) ----------
     Se a partitura exibida foi salva (scoreId + sessão), baixa pelo id
     (cópia autoritativa do servidor). Senão, POSTa score_data exibida
     para /api/score-midi.php. Mesmas notas da tela, sem aleatoriedade. */
  var MidiModule = {
    busy: false,

    currentPayload: function () {
      var cur = (typeof GeneratorModule !== 'undefined') ? GeneratorModule.current : null;
      if (!cur || !Array.isArray(cur.notes) || !cur.notes.length) return null;
      for (var i = 0; i < cur.notes.length; i++) {
        if (typeof cur.notes[i] !== 'object' || cur.notes[i] === null) return 'legacy';
      }
      var labels = cur.labels || {};
      return {
        title: cur.title || 'Partitura sem título',
        instrument: labels.instrumento || '',
        tom: labels.tom || '',
        andamento: labels.andamento || '',
        compasso: labels.compasso || cur.timeSignature || '',
        notes: cur.notes
      };
    },

    setBusy: function (busy) {
      this.busy = busy;
      var btn = document.getElementById('midi-btn');
      if (!btn) return;
      btn.disabled = busy;
      btn.setAttribute('aria-busy', String(busy));
      btn.textContent = busy ? 'Gerando MIDI…' : '♫ Baixar MIDI';
    },

    saveBlob: function (blob, filename) {
      var url = (window.URL && window.URL.createObjectURL) ? window.URL.createObjectURL(blob) : null;
      if (!url) throw new Error('Não foi possível preparar o download.');
      var a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.setTimeout(function () { window.URL.revokeObjectURL(url); }, 4000);
    },

    download: function () {
      if (this.busy) return;
      var self = this;
      var done = function () { self.setBusy(false); };
      var fail = function (message) {
        done();
        GeneratorModule.showFeedback(message || 'Erro ao gerar MIDI.', 'error');
      };
      var fromId = function (id) {
        window.fetch('/api/score-midi.php?id=' + encodeURIComponent(id), { headers: { 'Accept': 'audio/midi' } })
          .then(function (response) {
            if (!response.ok) throw new Error('Não foi possível gerar o MIDI.');
            return response.blob();
          })
          .then(function (blob) {
            self.saveBlob(blob, 'partitura.mid');
            done();
            GeneratorModule.showFeedback('Download do MIDI pronto.', 'success');
          })
          .catch(function () { fail('Erro ao gerar MIDI.'); });
      };
      var scoreId = (typeof GeneratorModule !== 'undefined') ? GeneratorModule.lastScoreId : null;
      var logged = (typeof ScoresModule !== 'undefined') ? ScoresModule.logged : false;
      if (scoreId && logged) {
        this.setBusy(true);
        fromId(scoreId);
        return;
      }
      var payload = this.currentPayload();
      if (payload === null) {
        GeneratorModule.showFeedback('Gere uma partitura antes de exportar o MIDI.', 'error');
        return;
      }
      if (payload === 'legacy') {
        GeneratorModule.showFeedback('Esta partitura salva não possui dados estruturais para o MIDI.', 'error');
        return;
      }
      this.setBusy(true);
      window.fetch('/api/score-midi.php', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'audio/midi' },
        body: JSON.stringify({ score: payload })
      }).then(function (response) {
        if (!response.ok) throw new Error('Não foi possível gerar o MIDI.');
        return response.blob();
      }).then(function (blob) {
        self.saveBlob(blob, 'partitura.mid');
        done();
        GeneratorModule.showFeedback('Download do MIDI pronto.', 'success');
      }).catch(function () { fail('Erro ao gerar MIDI.'); });
    },

    init: function () {
      var btn = document.getElementById('midi-btn');
      if (!btn) return;
      var self = this;
      btn.addEventListener('click', function () { self.download(); });
    }
  };

  /* ---------- Módulo: PDF (download da partitura atual) ----------
     POSTa score_data exibida para /api/score-pdf.php e baixa o retorno.
     Funciona para convidados e autenticados (só desenha o enviado). */
  var PdfModule = {
    busy: false,

    currentPayload: function () {
      var cur = (typeof GeneratorModule !== 'undefined') ? GeneratorModule.current : null;
      if (!cur || !Array.isArray(cur.notes) || !cur.notes.length) return null;
      for (var i = 0; i < cur.notes.length; i++) {
        if (typeof cur.notes[i] !== 'object' || cur.notes[i] === null) return 'legacy';
      }
      var labels = cur.labels || {};
      return {
        title: cur.title || 'Partitura sem título',
        instrument: labels.instrumento || '',
        tom: labels.tom || '',
        andamento: labels.andamento || '',
        compasso: labels.compasso || cur.timeSignature || '',
        dificuldade: labels.dificuldade || '',
        estilo: labels.estilo || '',
        notes: cur.notes
      };
    },

    setBusy: function (busy) {
      this.busy = busy;
      var btn = document.getElementById('pdf-btn');
      if (!btn) return;
      btn.disabled = busy;
      btn.setAttribute('aria-busy', String(busy));
      btn.innerHTML = busy
        ? 'Gerando PDF…'
        : '⤓ Baixar PDF';
    },

    download: function () {
      if (this.busy) return;
      var payload = this.currentPayload();
      if (payload === null) {
        GeneratorModule.showFeedback('Gere uma partitura antes de exportar o PDF.', 'error');
        return;
      }
      if (payload === 'legacy') {
        GeneratorModule.showFeedback('Esta partitura salva não possui dados estruturais para o PDF.', 'error');
        return;
      }
      var self = this;
      this.setBusy(true);
      window.fetch('/api/score-pdf.php', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/pdf' },
        body: JSON.stringify({ score: payload })
      }).then(function (response) {
        if (!response.ok) {
          return response.text().then(function (text) {
            var msg = 'Não foi possível gerar o PDF.';
            try {
              var data = JSON.parse(text);
              if (data && data.error) msg = data.error;
            } catch (e) { /* mantém mensagem padrão */ }
            throw new Error(msg);
          });
        }
        return response.blob();
      }).then(function (blob) {
        var url = (window.URL && window.URL.createObjectURL) ? window.URL.createObjectURL(blob) : null;
        if (!url) throw new Error('Não foi possível preparar o download.');
        var a = document.createElement('a');
        a.href = url;
        a.download = 'partitura.pdf';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.setTimeout(function () { window.URL.revokeObjectURL(url); }, 4000);
        self.setBusy(false);
      }).catch(function (err) {
        self.setBusy(false);
        GeneratorModule.showFeedback(err.message || 'Não foi possível gerar o PDF.', 'error');
      });
    },

    init: function () {
      var btn = document.getElementById('pdf-btn');
      if (!btn) return;
      var self = this;
      btn.addEventListener('click', function () { self.download(); });
    }
  };

  /* ---------- Módulo: Minhas Partituras (servidor, autenticado) ----------
     Lista, abre e exclui partituras do usuário da SESSÃO. O backend
     filtra tudo por user_id; o frontend nunca envia user_id. */
  var ScoresModule = {
    logged: false,

    fmtDate: function (iso) {
      try {
        return new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
      } catch (e) { return ''; }
    },

    sync: function (user) {
      this.logged = !!user;
      document.getElementById('server-list-login').hidden = this.logged;
      if (this.logged) this.refresh();
      else {
        document.getElementById('server-list').innerHTML = '';
        document.getElementById('server-list-empty').hidden = true;
      }
    },

    refresh: function () {
      var self = this;
      if (!this.logged) return Promise.resolve();
      return window.fetch('/api/scores.php', { headers: { 'Accept': 'application/json' } })
        .then(function (r) { return r.json().then(function (d) { return { status: r.status, body: d }; }); })
        .then(function (res) {
          if (res.status === 401) { self.sync(null); return; }
          if (!res.body || res.body.success !== true) return;
          self.render(res.body.scores || []);
        })
        .catch(function () { /* mantém lista atual em falha de rede */ });
    },

    render: function (scores) {
      var list = document.getElementById('server-list');
      list.innerHTML = '';
      document.getElementById('server-list-empty').hidden = scores.length > 0;
      scores.forEach(function (s) {
        var li = document.createElement('li');
        li.className = 'history__item';
        var title = document.createElement('p');
        title.className = 'history__desc';
        title.textContent = s.title || 'Sem título';
        li.appendChild(title);
        var meta = document.createElement('p');
        meta.className = 'history__meta';
        meta.textContent = [s.instrument, s.musical_key, s.style].filter(Boolean).join(' · ') + ' · ' + this.fmtDate(s.created_at);
        li.appendChild(meta);
        var actions = document.createElement('div');
        actions.className = 'history__actions';
        var open = document.createElement('button');
        open.type = 'button';
        open.className = 'link-btn';
        open.textContent = 'Abrir';
        open.setAttribute('data-open-score', s.id);
        open.setAttribute('aria-label', 'Abrir partitura ' + (s.title || ''));
        actions.appendChild(open);
        var del = document.createElement('button');
        del.type = 'button';
        del.className = 'link-btn link-btn--danger';
        del.textContent = 'Excluir';
        del.setAttribute('data-del-score', s.id);
        del.setAttribute('aria-label', 'Excluir partitura ' + (s.title || ''));
        actions.appendChild(del);
        var pdf = document.createElement('a');
        pdf.className = 'link-btn';
        pdf.textContent = 'PDF';
        pdf.href = '/api/score-pdf.php?id=' + encodeURIComponent(s.id);
        pdf.setAttribute('aria-label', 'Baixar PDF da partitura ' + (s.title || ''));
        actions.appendChild(pdf);
        var midi = document.createElement('a');
        midi.className = 'link-btn';
        midi.textContent = 'MIDI';
        midi.href = '/api/score-midi.php?id=' + encodeURIComponent(s.id);
        midi.setAttribute('aria-label', 'Baixar MIDI da partitura ' + (s.title || ''));
        actions.appendChild(midi);
        li.appendChild(actions);
        list.appendChild(li);
      }, this);
    },

    openScore: function (id) {
      window.fetch('/api/scores.php?id=' + encodeURIComponent(id), { headers: { 'Accept': 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data || data.success !== true || !data.score) return;
          var s = data.score;
          var sd = (s.score_data && typeof s.score_data === 'object') ? s.score_data : {};
          var notes = Array.isArray(sd.notes) && sd.notes.length ? sd.notes : [];
          GeneratorModule.renderResult({
            title: s.title || sd.title || 'Sem título',
            labels: (sd.labels && typeof sd.labels === 'object') ? sd.labels : {
              instrumento: s.instrument || '', tom: s.musical_key || '',
              andamento: s.tempo || '', compasso: s.time_signature || '', estilo: s.style || ''
            },
            tempo: (typeof sd.tempo === 'number') ? sd.tempo : null,
            notes: notes
          });
          GeneratorModule.showFeedback('Partitura "' + (s.title || 'Sem título') + '" carregada da sua conta.', 'success');
          GeneratorModule.lastScoreId = s.id || null;
          document.getElementById('criar').scrollIntoView({ behavior: 'smooth', block: 'start' });
        })
        .catch(function () { /* silencioso: lista continua válida */ });
    },

    init: function () {
      var list = document.getElementById('server-list');
      if (!list) return;
      var self = this;
      list.addEventListener('click', function (event) {
        var openBtn = event.target.closest('[data-open-score]');
        var delBtn = event.target.closest('[data-del-score]');
        if (openBtn) { self.openScore(openBtn.getAttribute('data-open-score')); return; }
        if (delBtn) {
          var id = delBtn.getAttribute('data-del-score');
          if (!window.confirm('Excluir esta partitura da sua conta?')) return;
          window.fetch('/api/scores.php?id=' + encodeURIComponent(id), { method: 'DELETE', headers: { 'Accept': 'application/json' } })
            .then(function () { self.refresh(); })
            .catch(function () { self.refresh(); });
        }
      });
    }
  };

  /* ---------- Módulo: Autenticação (sessão PHP + Neon) ---------- */
  var AuthModule = {
    modal: null,
    lastFocus: null,

    postJSON: function (url, payload) {
      return window.fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(payload)
      }).then(function (response) {
        return response.text().then(function (text) {
          var data = null;
          try { data = JSON.parse(text); } catch (e) { data = null; }
          if (!response.ok || !data || data.success !== true) {
            throw new Error((data && data.error) || ('Erro (HTTP ' + response.status + ').'));
          }
          return data;
        });
      });
    },

    open: function (tab) {
      if (!this.modal) return;
      this.lastFocus = document.activeElement;
      this.switchTab(tab === 'register' ? 'register' : 'login');
      this.modal.hidden = false;
      var input = this.modal.querySelector('form:not([hidden]) input');
      if (input) input.focus();
    },

    close: function () {
      if (!this.modal) return;
      this.modal.hidden = true;
      if (this.lastFocus && this.lastFocus.focus) this.lastFocus.focus({ preventScroll: true });
    },

    switchTab: function (tab) {
      var isLogin = tab !== 'register';
      document.getElementById('login-form').hidden = !isLogin;
      document.getElementById('register-form').hidden = isLogin;
      document.getElementById('tab-login').classList.toggle('is-active', isLogin);
      document.getElementById('tab-register').classList.toggle('is-active', !isLogin);
      document.getElementById('tab-login').setAttribute('aria-selected', String(isLogin));
      document.getElementById('tab-register').setAttribute('aria-selected', String(!isLogin));
      document.getElementById('auth-title').textContent = isLogin ? 'Entrar' : 'Criar conta';
    },

    showMsg: function (id, text, kind) {
      var el = document.getElementById(id);
      el.hidden = false;
      el.textContent = text;
      el.classList.toggle('auth-msg--success', kind === 'success');
    },

    setUser: function (user) {
      var logged = !!user;
      this.user = user || null;
      document.querySelectorAll('.js-open-auth').forEach(function (b) { b.hidden = logged; });
      [['user-chip', 'user-name'], ['user-chip-mobile', 'user-name-mobile']].forEach(function (pair) {
        var chip = document.getElementById(pair[0]);
        if (!chip) return;
        chip.hidden = !logged;
        if (logged) document.getElementById(pair[1]).textContent = user.name;
      });
      if (typeof ScoresModule !== 'undefined') ScoresModule.sync(user);
    },

    refresh: function () {
      var self = this;
      window.fetch('/api/session.php', { headers: { 'Accept': 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          self.setUser(data && data.authenticated ? data.user : null);
        })
        .catch(function () { /* sem sessão: mantém estado deslogado */ });
    },

    bindForm: function (formId, url, msgId, getPayload) {
      var self = this;
      var form = document.getElementById(formId);
      if (!form) return;
      form.addEventListener('submit', function (event) {
        event.preventDefault();
        var btn = form.querySelector('[type="submit"]');
        btn.disabled = true;
        self.postJSON(url, getPayload(form))
          .then(function (data) {
            self.showMsg(msgId, 'Bem-vindo(a), ' + data.user.name + '!', 'success');
            window.setTimeout(function () { self.close(); self.refresh(); }, 700);
          })
          .catch(function (err) {
            self.showMsg(msgId, err.message || 'Erro. Tente novamente.');
          })
          .then(function () { btn.disabled = false; });
      });
    },

    init: function () {
      this.modal = document.getElementById('auth-modal');
      if (!this.modal) return;
      var self = this;

      document.querySelectorAll('.js-open-auth').forEach(function (btn) {
        btn.addEventListener('click', function () { self.open('login'); });
      });
      document.querySelectorAll('.js-logout').forEach(function (btn) {
        btn.addEventListener('click', function () {
          self.postJSON('/api/logout.php', {}).then(function () { self.refresh(); }).catch(function () { self.refresh(); });
        });
      });
      this.modal.querySelectorAll('[data-close-auth]').forEach(function (el) {
        el.addEventListener('click', function () { self.close(); });
      });
      document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && !self.modal.hidden) self.close();
      });
      document.querySelectorAll('[data-auth-tab]').forEach(function (tab) {
        tab.addEventListener('click', function () { self.switchTab(tab.getAttribute('data-auth-tab')); });
      });

      this.bindForm('login-form', '/api/login.php', 'login-msg', function (form) {
        return { email: form.email.value.trim(), password: form.password.value };
      });
      this.bindForm('register-form', '/api/register.php', 'register-msg', function (form) {
        return { name: form.name.value.trim(), email: form.email.value.trim(), password: form.password.value };
      });

      this.refresh();
    }
  };

  /* ---------- Módulo: Interações informativas ---------- */
  var InfoActionsModule = {
    MESSAGES: {
      termos: 'Os Termos de Uso serão publicados em uma próxima etapa do projeto.',
      privacidade: 'A Política de Privacidade será publicada em uma próxima etapa do projeto.'
    },

    init: function () {
      document.addEventListener('click', function (event) {
        var el = event.target.closest('[data-action]');
        if (!el) return;
        var action = el.getAttribute('data-action');
        var message = this.MESSAGES[action];
        if (!message) return; // ações de navegação seguem o fluxo padrão

        event.preventDefault();
        this.show(message, el.getAttribute('href'));
      }.bind(this));
    },

    show: function (message, target) {
      var feedback = document.getElementById('demo-feedback');
      // Reutiliza a área de status da demo quando existir; senão, usa alert simples via região viva temporária
      if (feedback && target !== '#') {
        feedback.hidden = false;
        feedback.textContent = message;
        var demo = document.getElementById('exemplo');
        if (demo) demo.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
      }
      window.alert(message);
    }
  };

  /* ---------- Módulo: UI da referência (somente visual) -----
     Adapta o layout à imagem de referência sem tocar em geração,
     OpenRouter, Neon, auth, PDF, MIDI, player ou endpoints.
     Apenas sincroniza selects/abas com os inputs originais e
     adiciona MusicXML (client-side), Detalhes, busca e extras
     do player por observação (sem alterar os módulos base). */
  var RefUiModule = {
    BPM: { 'Muito lento': 50, 'Lento': 70, 'Moderado': 96, 'Rápido': 128, 'Muito rápido': 160 },
    vol: 0.8,

    setRadio: function (name, value) {
      var form = document.getElementById('generator-form');
      if (!form || !value) return false;
      var input = form.querySelector('input[name="' + name + '"][value="' + value + '"]');
      if (input) { input.checked = true; return true; }
      return false;
    },

    getRadio: function (name) {
      var form = document.getElementById('generator-form');
      if (!form) return '';
      var checked = form.querySelector('input[name="' + name + '"]:checked');
      return checked ? checked.value : '';
    },

    syncSelectsFromRadios: function () {
      var map = { 'instrumento': 'instrumento-sel', 'estilo': 'estilo-sel', 'compasso': 'compasso-sel' };
      Object.keys(map).forEach(function (name) {
        var sel = document.getElementById(map[name]);
        if (!sel) return;
        var v = this.getRadio(name);
        if (v && sel.querySelector('option[value="' + v + '"]')) sel.value = v;
      }, this);
      this.updateBpmBadge();
    },

    updateBpmBadge: function () {
      var and = document.getElementById('andamento');
      var badge = document.getElementById('andamento-bpm');
      if (and && badge && this.BPM[and.value]) badge.textContent = this.BPM[and.value] + ' BPM';
      this.updatePreviewMeta();
    },

    tomEn: function (tom) {
      if (!tom) return '';
      return tom.replace('Maior', 'Major').replace('Menor', 'Minor');
    },

    updatePreviewMeta: function () {
      var meta = document.getElementById('preview-meta');
      if (!meta) return;
      var cur = (typeof GeneratorModule !== 'undefined' && GeneratorModule.current) ? GeneratorModule.current : null;
      var labels = (cur && cur.labels) || {};
      var inst = labels.instrumento || ((document.getElementById('instrumento-sel') || {}).value || 'Piano');
      var tom = this.tomEn(labels.tom || ((document.getElementById('tom') || {}).value || 'C Maior'));
      var comp = labels.compasso || cur.timeSignature || ((document.getElementById('compasso-sel') || {}).value || '3/4');
      var bpm = (cur && typeof cur.tempo === 'number') ? cur.tempo : (this.BPM[labels.andamento] || this.BPM[((document.getElementById('andamento') || {}).value)] || 90);
      meta.innerHTML = inst + '&nbsp;&nbsp;&nbsp;' + tom + ' • ' + comp + '<br />Andamento: ' + bpm + ' BPM';
    },

    initTabs: function () {
      var tabs = Array.prototype.slice.call(document.querySelectorAll('[data-gtab]'));
      var panels = Array.prototype.slice.call(document.querySelectorAll('[data-gpanel]'));
      if (!tabs.length || !panels.length) return;
      var activate = function (name, focus) {
        tabs.forEach(function (t) {
          var on = t.getAttribute('data-gtab') === name;
          t.classList.toggle('is-active', on);
          t.setAttribute('aria-selected', String(on));
          t.tabIndex = on ? 0 : -1;
          if (on && focus) t.focus();
        });
        panels.forEach(function (p) { p.hidden = p.getAttribute('data-gpanel') !== name; });
      };
      tabs.forEach(function (t, i) {
        t.addEventListener('click', function () { activate(t.getAttribute('data-gtab'), false); });
        t.addEventListener('keydown', function (e) {
          var j = null;
          if (e.key === 'ArrowRight') j = (i + 1) % tabs.length;
          else if (e.key === 'ArrowLeft') j = (i - 1 + tabs.length) % tabs.length;
          else if (e.key === 'Home') j = 0;
          else if (e.key === 'End') j = tabs.length - 1;
          if (j !== null) { e.preventDefault(); activate(tabs[j].getAttribute('data-gtab'), true); }
        });
      });
    },

    initSelects: function () {
      var self = this;
      var bind = function (selId, name) {
        var sel = document.getElementById(selId);
        if (!sel) return;
        sel.addEventListener('change', function () { self.setRadio(name, sel.value); self.updatePreviewMeta(); });
      };
      bind('instrumento-sel', 'instrumento');
      bind('estilo-sel', 'estilo');
      bind('compasso-sel', 'compasso');
      var form = document.getElementById('generator-form');
      if (form) {
        form.addEventListener('change', function (e) {
          var t = e.target;
          if (t && t.name === 'instrumento' && t.value) { var s = document.getElementById('instrumento-sel'); if (s) s.value = t.value; }
          if (t && t.name === 'estilo' && t.value) { var s2 = document.getElementById('estilo-sel'); if (s2) s2.value = t.value; }
          if (t && t.name === 'compasso' && t.value) { var s3 = document.getElementById('compasso-sel'); if (s3) s3.value = t.value; }
          self.updatePreviewMeta();
        });
        document.addEventListener('click', function (e) {
          if (e.target && e.target.closest && e.target.closest('[data-load]')) {
            window.setTimeout(function () { self.syncSelectsFromRadios(); }, 200);
          }
        });
      }
      var and = document.getElementById('andamento');
      if (and) and.addEventListener('change', function () { self.updateBpmBadge(); });
      var tom = document.getElementById('tom');
      if (tom) tom.addEventListener('change', function () { self.updatePreviewMeta(); });
      this.syncSelectsFromRadios();
    },

    initSearch: function () {
      var input = document.getElementById('busca');
      if (!input) return;
      input.addEventListener('input', function () {
        var q = input.value.trim().toLowerCase();
        var cards = document.querySelectorAll('#recentes-grid .rec-card, #historico-lista li, #server-list li');
        cards.forEach(function (el) {
          el.style.display = (!q || (el.textContent || '').toLowerCase().indexOf(q) !== -1) ? '' : 'none';
        });
      });
    },

    initExplore: function () {
      var self = this;
      document.querySelectorAll('[data-estilo]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var v = btn.getAttribute('data-estilo');
          self.setRadio('estilo', v);
          var sel = document.getElementById('estilo-sel');
          if (sel && sel.querySelector('option[value="' + v + '"]')) sel.value = v;
          var target = document.getElementById('criar');
          if (target && target.scrollIntoView) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
          if (typeof GeneratorModule !== 'undefined') GeneratorModule.showFeedback('Estilo "' + v + '" selecionado. Descreva sua música e clique em Gerar.', 'success');
        });
      });
      var presets = {
        valsa: { d: 'Uma valsa calma e simples para piano, estilo clássico.', instrumento: 'Piano', estilo: 'Clássico', tom: 'C Maior', andamento: 'Moderado', compasso: '3/4' },
        noite: { d: 'Uma música tranquila para violão, estilo popular e calmo.', instrumento: 'Violão', estilo: 'Pop', tom: 'G Maior', andamento: 'Lento', compasso: '4/4' },
        aventura: { d: 'Um tema de aventura épico para trilha sonora de filme.', instrumento: 'Piano', estilo: 'Cinematográfico', tom: 'D Menor', andamento: 'Rápido', compasso: '4/4' },
        estudo: { d: 'Um estudo simples em dó maior para piano iniciante.', instrumento: 'Piano', estilo: 'Clássico', tom: 'C Maior', andamento: 'Moderado', compasso: '2/4' },
        manha: { d: 'Uma canção alegre da manhã para piano, estilo popular.', instrumento: 'Piano', estilo: 'Pop', tom: 'F Maior', andamento: 'Moderado', compasso: '4/4' },
        melodia: { d: 'Uma melodia simples e calma para flauta.', instrumento: 'Flauta', estilo: 'Pop', tom: 'C Maior', andamento: 'Lento', compasso: '3/4' }
      };
      document.querySelectorAll('[data-exemplo]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var p = presets[btn.getAttribute('data-exemplo')] || presets.valsa;
          var desc = document.getElementById('descricao');
          if (desc) { desc.value = p.d; desc.dispatchEvent(new Event('input', { bubbles: true })); }
          self.setRadio('instrumento', p.instrumento);
          self.setRadio('estilo', p.estilo);
          self.setRadio('compasso', p.compasso);
          var tom = document.getElementById('tom'); if (tom) tom.value = p.tom;
          var and = document.getElementById('andamento'); if (and) and.value = p.andamento;
          self.syncSelectsFromRadios();
          var target = document.getElementById('criar');
          if (target && target.scrollIntoView) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
          if (typeof GeneratorModule !== 'undefined') GeneratorModule.showFeedback('Exemplo carregado. Clique em "Gerar Partitura com IA".', 'success');
        });
      });
      var ouvir = document.getElementById('ouvir-exemplo');
      if (ouvir) ouvir.addEventListener('click', function () {
        var play = document.getElementById('play-btn');
        if (play) play.click();
      });
    },

    escXml: function (s) {
      return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },

    initMusicXml: function () {
      var self = this;
      var btn = document.getElementById('musicxml-btn');
      if (!btn) return;
      btn.addEventListener('click', function () {
        var cur = (typeof GeneratorModule !== 'undefined') ? GeneratorModule.current : null;
        if (!cur || !Array.isArray(cur.notes) || !cur.notes.length) {
          GeneratorModule.showFeedback('Gere uma partitura antes de exportar o MusicXML.', 'error');
          return;
        }
        var labels = cur.labels || {};
        var beats = (typeof cur.timeSignature === 'string' && cur.timeSignature.indexOf('/') !== -1)
          ? cur.timeSignature.split('/') : ['4', '4'];
        var bpm = (typeof cur.tempo === 'number') ? cur.tempo : 96;
        var types = { whole: ['whole', 16], half: ['half', 8], quarter: ['quarter', 4], eighth: ['eighth', 2], sixteenth: ['16th', 1] };
        var xml = '<?xml version="1.0" encoding="UTF-8"?>\n<score-partwise version="3.1">\n';
        xml += '<work><work-title>' + self.escXml(cur.title || 'Partitura') + '</work-title></work>\n';
        xml += '<part-list><score-part id="P1"><part-name>' + self.escXml(labels.instrumento || 'Piano') + '</part-name></score-part></part-list>\n';
        xml += '<part id="P1">\n<measure number="1">\n<attributes>\n<divisions>4</divisions>\n';
        xml += '<time><beats>' + self.escXml(beats[0]) + '</beats><beat-type>' + self.escXml(beats[1]) + '</beat-type></time>\n';
        xml += '<clef><sign>G</sign><line>2</line></clef>\n</attributes>\n';
        xml += '<direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>' + bpm + '</per-minute></metronome></direction-type><sound tempo="' + bpm + '"/></direction>\n';
        cur.notes.forEach(function (n) {
          var t = types[n.duration] || types.quarter;
          xml += '<note>';
          if (n.rest) { xml += '<rest/><duration>' + t[1] + '</duration><type>' + t[0] + '</type>'; }
          else {
            var pitch = String(n.pitch || 'C');
            var step = pitch.charAt(0);
            var alter = pitch.indexOf('#') !== -1 ? '<alter>1</alter>' : '';
            xml += '<pitch><step>' + step + '</step>' + alter + '<octave>' + (n.octave == null ? 4 : n.octave) + '</octave></pitch>';
            xml += '<duration>' + t[1] + '</duration><type>' + t[0] + '</type>';
          }
          xml += '</note>\n';
        });
        xml += '</measure>\n</part>\n</score-partwise>\n';
        var blob = new Blob([xml], { type: 'application/vnd.recordare.musicxml+xml' });
        var url = (window.URL && window.URL.createObjectURL) ? window.URL.createObjectURL(blob) : null;
        if (!url) { GeneratorModule.showFeedback('Não foi possível preparar o download.', 'error'); return; }
        var a = document.createElement('a');
        a.href = url;
        a.download = 'partitura.musicxml';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.setTimeout(function () { window.URL.revokeObjectURL(url); }, 4000);
        GeneratorModule.showFeedback('Download do MusicXML pronto.', 'success');
      });
    },

    initDetalhes: function () {
      var open = document.getElementById('detalhes-btn');
      var modal = document.getElementById('detalhes-modal');
      var list = document.getElementById('detalhes-list');
      if (!open || !modal || !list) return;
      var close = function () { modal.hidden = true; };
      open.addEventListener('click', function () {
        var cur = (typeof GeneratorModule !== 'undefined' && GeneratorModule.current) ? GeneratorModule.current : null;
        var labels = (cur && cur.labels) || {};
        var rows = [
          ['Título', (cur && cur.title) || '—'],
          ['Instrumento', labels.instrumento || '—'],
          ['Tom', labels.tom || '—'],
          ['Andamento', labels.andamento || '—'],
          ['Compasso', labels.compasso || ((cur && cur.timeSignature) || '—')],
          ['Tempo', (cur && typeof cur.tempo === 'number') ? ('♩ = ' + cur.tempo) : '—'],
          ['Notas', (cur && cur.notes) ? String(cur.notes.length) : '0']
        ];
        list.innerHTML = '';
        rows.forEach(function (r) {
          var dt = document.createElement('dt'); dt.textContent = r[0];
          var dd = document.createElement('dd'); dd.textContent = r[1];
          list.appendChild(dt); list.appendChild(dd);
        });
        modal.hidden = false;
        var c = modal.querySelector('[data-close-detalhes].modal__close');
        if (c) c.focus();
      });
      modal.querySelectorAll('[data-close-detalhes]').forEach(function (el) {
        el.addEventListener('click', close);
      });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !modal.hidden) close();
      });
    },

    fmtTime: function (s) {
      s = Math.max(0, Math.floor(s || 0));
      return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
    },

    initPlayerExtras: function () {
      var self = this;
      var bar = document.getElementById('player-progress');
      var time = document.getElementById('player-time');
      var vol = document.getElementById('volume');
      if (vol) {
        vol.addEventListener('input', function () {
          self.vol = (parseInt(vol.value, 10) || 0) / 100;
          if (typeof PlayerModule !== 'undefined' && PlayerModule.master) {
            try { PlayerModule.master.gain.value = self.vol * 0.9; } catch (e) { /* sem áudio */ }
          }
        });
      }
      var dl = document.getElementById('player-download');
      if (dl) dl.addEventListener('click', function () {
        if (typeof PdfModule !== 'undefined') PdfModule.download();
      });
      var ex = document.getElementById('player-expand');
      if (ex) ex.addEventListener('click', function () {
        var card = document.getElementById('score-preview');
        if (!card) return;
        if (document.fullscreenElement) { document.exitFullscreen(); return; }
        if (card.requestFullscreen) card.requestFullscreen();
      });
      if (!bar || !time) return;
      window.setInterval(function () {
        try {
          if (typeof PlayerModule === 'undefined' || PlayerModule.state !== 'playing' || !PlayerModule.ctx || !PlayerModule.timeline.length) return;
          var last = PlayerModule.timeline[PlayerModule.timeline.length - 1];
          var total = last.start + last.dur;
          var elapsed = PlayerModule.ctx.currentTime - PlayerModule.startedAt;
          if (total > 0) {
            bar.value = String(Math.min(100, Math.max(0, Math.round((elapsed / total) * 100))));
            time.textContent = self.fmtTime(elapsed) + ' / ' + self.fmtTime(total);
          }
          if (PlayerModule.master) PlayerModule.master.gain.value = self.vol * 0.9;
        } catch (e) { /* observação apenas */ }
      }, 300);
    },

    initPreviewObserver: function () {
      var self = this;
      var target = document.getElementById('resultado-sim');
      if (target && typeof MutationObserver === 'function') {
        var obs = new MutationObserver(function () { self.updatePreviewMeta(); });
        obs.observe(target, { childList: true, subtree: true, characterData: true });
      }
      this.updatePreviewMeta();
    },

    init: function () {
      this.initTabs();
      this.initSelects();
      this.initSearch();
      this.initExplore();
      this.initMusicXml();
      this.initDetalhes();
      this.initPlayerExtras();
      this.initPreviewObserver();
    }
  };

  /* ---------- Módulo: Detalhes de interface ---------- */
  var UiModule = {
    initYear: function () {
      var year = document.getElementById('ano');
      if (year) year.textContent = String(new Date().getFullYear());
    },

    initReveal: function () {
      var items = document.querySelectorAll('.reveal');
      if (!items.length) return;
      if (!('IntersectionObserver' in window)) {
        items.forEach(function (el) { el.classList.add('is-visible'); });
        return;
      }
      var observer = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              entry.target.classList.add('is-visible');
              observer.unobserve(entry.target);
            }
          });
        },
        { threshold: 0.12 }
      );
      items.forEach(function (el) { observer.observe(el); });
    },

    init: function () {
      this.initYear();
      this.initReveal();
    }
  };

  /* ---------- Bootstrap ---------- */
  function init() {
    ThemeModule.init();
    MenuModule.init();
    DemoModule.init();
    GeneratorModule.init();
    AuthModule.init();
    ScoresModule.init();
    PlayerModule.init();
    PdfModule.init();
    MidiModule.init();
    RefUiModule.init();
    InfoActionsModule.init();
    UiModule.init();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
