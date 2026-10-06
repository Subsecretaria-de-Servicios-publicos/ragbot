/*!
 * RAGBot Widget v1.0
 * Widget embebible como globo flotante o página completa
 * Uso: <script src="URL/static/widget.js"></script>
 *      window.RAGBot.init({ botId, apiUrl, primaryColor, position })
 */
(function(window) {
  'use strict';

  // ─── CSS ───────────────────────────────────────────────────
  const CSS = `
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

    #ragbot-container * { box-sizing: border-box; font-family: 'Inter', sans-serif; }

    /* Floating Button */
    #ragbot-trigger {
      position: fixed;
      width: 56px; height: 56px;
      border-radius: 50%;
      background: var(--rb-color, #6c63ff);
      border: none; cursor: pointer;
      box-shadow: 0 4px 20px rgba(0,0,0,0.25);
      display: flex; align-items: center; justify-content: center;
      font-size: 24px;
      z-index: 999998;
      transition: transform 0.2s, box-shadow 0.2s;
      animation: rbPulse 3s infinite;
    }
    #ragbot-trigger:hover { transform: scale(1.08); box-shadow: 0 6px 28px rgba(0,0,0,0.3); }
    @keyframes rbPulse {
      0%, 100% { box-shadow: 0 4px 20px rgba(0,0,0,0.25); }
      50% { box-shadow: 0 4px 28px var(--rb-color, #6c63ff), 0 0 0 8px rgba(108,99,255,0.12); }
    }
    #ragbot-trigger.bottom-right { bottom: 24px; right: 24px; }
    #ragbot-trigger.bottom-left { bottom: 24px; left: 24px; }
    #ragbot-trigger.top-right { top: 24px; right: 24px; }

    /* Notification badge */
    #ragbot-badge {
      position: absolute; top: -4px; right: -4px;
      background: #ef4444; color: #fff;
      width: 18px; height: 18px; border-radius: 50%;
      font-size: 10px; font-weight: 700;
      display: none; align-items: center; justify-content: center;
    }

    /* Chat Window */
    #ragbot-window {
      position: fixed;
      /* ancla para #rb-help-menu (position: absolute) */
      width: 380px;
      height: 560px;
      background: #ffffff;
      border-radius: 16px;
      box-shadow: 0 20px 60px rgba(0,0,0,0.2);
      z-index: 999999;
      display: none;
      flex-direction: column;
      overflow: hidden;
      animation: rbSlideIn 0.25s cubic-bezier(0.34,1.56,0.64,1);
    }
    @keyframes rbSlideIn { from { opacity:0; transform: scale(0.85) translateY(20px); } }

    #ragbot-window.open { display: flex; }
    #ragbot-window.bottom-right { bottom: 92px; right: 24px; }
    #ragbot-window.bottom-left { bottom: 92px; left: 24px; }
    #ragbot-window.top-right { top: 92px; right: 24px; }

    /* Header */
    #rb-header {
      background: linear-gradient(135deg, var(--rb-color, #6c63ff), var(--rb-color2, #a78bfa));
      padding: 14px 16px;
      display: flex; align-items: center; gap: 10px;
      flex-shrink: 0;
    }
    #rb-gov-logo { height: 26px; width: auto; border-radius: 4px; flex-shrink: 0; }
    #rb-org-logo { height: 26px; width: auto; border-radius: 4px; flex-shrink: 0; }
    #rb-avatar {
      width: 36px; height: 36px; border-radius: 50%;
      background: rgba(255,255,255,0.25);
      display: flex; align-items: center; justify-content: center;
      font-size: 18px; flex-shrink: 0;
    }
    #rb-header-info { flex: 1; }
    #rb-bot-name { color: #fff; font-size: 14px; font-weight: 600; }
    #rb-status { font-size: 11px; color: rgba(255,255,255,0.75); display: flex; align-items: center; gap: 4px; }
    .rb-dot { width: 6px; height: 6px; border-radius: 50%; background: #4ade80; animation: rbBlink 2s infinite; }
    @keyframes rbBlink { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
    #rb-close-btn {
      background: rgba(255,255,255,0.15); border: none; cursor: pointer;
      color: #fff; width: 28px; height: 28px; border-radius: 50%;
      font-size: 16px; display: flex; align-items: center; justify-content: center;
      transition: background 0.15s;
    }
    #rb-close-btn:hover { background: rgba(255,255,255,0.25); }
    #rb-help-btn {
      background: rgba(255,255,255,0.18); border: none; cursor: pointer; color: #fff;
      width: 28px; height: 28px; border-radius: 50%; font-size: 14px; flex-shrink: 0;
      display: flex; align-items: center; justify-content: center; transition: background 0.15s;
    }
    #rb-help-btn:hover { background: rgba(255,255,255,0.3); }
    #rb-help-menu {
      display: none; position: absolute; top: 66px; right: 12px; background: #fff;
      border-radius: 10px; box-shadow: 0 8px 24px rgba(0,0,0,0.18); overflow: hidden;
      min-width: 210px; z-index: 5;
    }
    #rb-help-menu.open { display: block; }
    #rb-help-menu a, #rb-help-menu button {
      display: flex; align-items: center; gap: 10px; padding: 11px 14px; font-size: 12.5px;
      color: #333; text-decoration: none; border-bottom: 1px solid #f0f0f5;
      background: none; border-left: none; border-right: none; border-top: none;
      width: 100%; text-align: left; cursor: pointer; font-family: inherit;
    }
    #rb-help-menu a:last-child, #rb-help-menu button:last-child { border-bottom: none; }
    #rb-help-menu a:hover, #rb-help-menu button:hover { background: #f8f8fc; }

    /* Formulario "hablar con una persona" */
    #rb-contact-form {
      display: none; position: absolute; inset: 0; background: #fff; z-index: 6;
      flex-direction: column;
    }
    #rb-contact-form.open { display: flex; }
    .rb-cf-header {
      background: linear-gradient(135deg, var(--rb-color, #6c63ff), var(--rb-color2, #a78bfa));
      color: #fff; padding: 14px 16px; display: flex; align-items: center;
      justify-content: space-between; flex-shrink: 0; font-size: 14px; font-weight: 600;
    }
    .rb-cf-header button {
      background: rgba(255,255,255,0.18); border: none; cursor: pointer; color: #fff;
      width: 26px; height: 26px; border-radius: 50%; font-size: 13px;
      display: flex; align-items: center; justify-content: center;
    }
    .rb-cf-body { padding: 16px; overflow-y: auto; flex: 1; }
    .rb-cf-body label {
      display: block; font-size: 12px; font-weight: 600; color: #555; margin-bottom: 4px; margin-top: 12px;
    }
    .rb-cf-body label:first-child { margin-top: 0; }
    .rb-cf-body input, .rb-cf-body textarea {
      width: 100%; box-sizing: border-box; padding: 8px 11px; border: 1.5px solid #e5e5ef;
      border-radius: 8px; font-size: 13px; font-family: inherit; outline: none; resize: vertical;
    }
    .rb-cf-body input:focus, .rb-cf-body textarea:focus { border-color: var(--rb-color, #6c63ff); }
    .rb-cf-hint { font-size: 11px; color: #999; margin-top: 10px; }
    .rb-cf-error { font-size: 12px; color: #ef4444; margin-top: 10px; display: none; }
    .rb-cf-error.show { display: block; }
    .rb-cf-submit {
      width: 100%; margin-top: 14px; background: var(--rb-color, #6c63ff); color: #fff;
      border: none; border-radius: 8px; padding: 11px; font-size: 13.5px; font-weight: 600;
      cursor: pointer; transition: filter 0.15s;
    }
    .rb-cf-submit:hover { filter: brightness(1.08); }
    .rb-cf-submit:disabled { opacity: 0.6; cursor: wait; }
    .rb-cf-wa {
      display: block; text-align: center; margin-top: 10px; font-size: 12px;
      color: var(--rb-color, #6c63ff); text-decoration: none;
    }
    .rb-cf-wa:hover { text-decoration: underline; }

    /* Messages */
    #rb-messages {
      flex: 1; overflow-y: auto; padding: 16px;
      display: flex; flex-direction: column; gap: 12px;
      scroll-behavior: smooth;
    }
    #rb-messages::-webkit-scrollbar { width: 4px; }
    #rb-messages::-webkit-scrollbar-thumb { background: #e0e0e0; border-radius: 2px; }

    .rb-msg { display: flex; gap: 8px; align-items: flex-end; }
    .rb-msg.user { flex-direction: row-reverse; }

    .rb-msg-avatar {
      width: 28px; height: 28px; border-radius: 50%;
      background: var(--rb-color, #6c63ff);
      display: flex; align-items: center; justify-content: center;
      font-size: 13px; flex-shrink: 0; color: #fff;
    }
    .rb-msg.user .rb-msg-avatar { background: #f0f0f5; color: #666; }

    .rb-bubble {
      max-width: 75%;
      padding: 10px 14px;
      border-radius: 16px;
      font-size: 13.5px;
      line-height: 1.5;
    }
    .rb-msg.bot .rb-bubble {
      background: var(--rb-bubble-bg, #f5f5f8);
      border-bottom-left-radius: 4px;
      color: #1a1a2e;
    }
    .rb-msg.user .rb-bubble {
      background: var(--rb-color, #6c63ff);
      color: #fff;
      border-bottom-right-radius: 4px;
    }
    .rb-bubble a { color: inherit; font-weight: 600; text-decoration: underline; }

    .rb-sources {
      margin-top: 6px; font-size: 11px; color: #888;
      display: flex; flex-wrap: wrap; gap: 4px;
    }
    .rb-source-tag {
      background: #ebebf5; color: #666; padding: 2px 8px;
      border-radius: 20px; font-size: 11px;
    }

    .rb-time { font-size: 10px; color: #bbb; margin-top: 4px; text-align: right; }

    .rb-contact-prompt { margin-top: 6px; font-size: 11px; color: #999; }
    .rb-contact-chips { display: flex; gap: 6px; margin-top: 5px; flex-wrap: wrap; }
    .rb-contact-chip {
      display: inline-flex; align-items: center; gap: 4px; background: #fff;
      border: 1.5px solid var(--rb-color, #6c63ff); color: var(--rb-color, #6c63ff);
      border-radius: 12px; padding: 5px 10px; font-size: 11.5px; text-decoration: none;
      transition: background 0.15s, color 0.15s;
    }
    .rb-contact-chip:hover { background: var(--rb-color, #6c63ff); color: #fff; }

    .rb-suggestions { display: flex; flex-direction: column; gap: 6px; padding: 0 16px 4px 44px; }
    .rb-suggestion-btn {
      align-self: flex-start; background: #fff; border: 1.5px solid var(--rb-color, #6c63ff);
      color: var(--rb-color, #6c63ff); border-radius: 14px; padding: 7px 12px; font-size: 12.5px;
      text-align: left; cursor: pointer; transition: background 0.15s, color 0.15s;
    }
    .rb-suggestion-btn:hover { background: var(--rb-color, #6c63ff); color: #fff; }

    /* Typing indicator */
    .rb-typing { display: flex; align-items: center; gap: 4px; padding: 10px 14px;
      background: #f5f5f8; border-radius: 16px; border-bottom-left-radius: 4px; width: fit-content; }
    .rb-typing span {
      width: 7px; height: 7px; background: #aaa; border-radius: 50%;
      animation: rbDot 1.4s infinite;
    }
    .rb-typing span:nth-child(2) { animation-delay: 0.2s; }
    .rb-typing span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes rbDot { 0%,80%,100% { transform: scale(0.6); opacity:0.4; } 40% { transform: scale(1); opacity:1; } }

    /* Input area */
    #rb-input-area {
      padding: 12px 16px;
      border-top: 1px solid #f0f0f5;
      display: flex; gap: 8px; align-items: flex-end;
      flex-shrink: 0;
    }
    #rb-input {
      flex: 1; padding: 9px 14px;
      border: 1.5px solid #e8e8f0;
      border-radius: 20px;
      font-size: 13.5px;
      outline: none; resize: none;
      font-family: inherit;
      max-height: 100px;
      line-height: 1.4;
      transition: border-color 0.15s;
    }
    #rb-input:focus { border-color: var(--rb-color, #6c63ff); }
    #rb-send {
      width: 38px; height: 38px; border-radius: 50%;
      background: var(--rb-color, #6c63ff);
      border: none; cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      flex-shrink: 0; transition: all 0.15s;
    }
    #rb-send:hover { filter: brightness(1.1); transform: scale(1.05); }
    #rb-send svg { width: 16px; height: 16px; }
    #rb-attach {
      width: 38px; height: 38px; border-radius: 50%; flex-shrink: 0;
      background: #f0f0f5; border: none; cursor: pointer; font-size: 16px;
      display: flex; align-items: center; justify-content: center; transition: background 0.15s;
    }
    #rb-attach:hover { background: #e5e5ef; }
    #rb-attach:disabled { opacity: 0.5; cursor: wait; }
    .rb-upload-note { font-size: 11px; color: #999; padding: 0 16px 6px; }

    #rb-footer { padding: 6px 12px 10px; text-align: center; }
    #rb-footer a { font-size: 10px; color: #ccc; text-decoration: none; }
    #rb-footer a:hover { color: #999; }
    /* El logo de Modernización es blanco: va sobre el mismo degradé del header */
    #rb-footer.rb-footer-logo {
      padding: 9px 12px; display: flex; justify-content: center; align-items: center;
      background: linear-gradient(135deg, var(--rb-color, #6c63ff), var(--rb-color2, #a78bfa));
    }
    #rb-footer-logo { max-height: 26px; max-width: 75%; width: auto; object-fit: contain; display: block; }
  `;

  // ─── RAGBot Widget Class ────────────────────────────────────
  class RAGBotWidget {
    constructor(config) {
      this.config = {
        botId: config.botId,
        apiUrl: (config.apiUrl || 'http://localhost:8000').replace(/\/$/, ''),
        primaryColor: config.primaryColor || '#6c63ff',
        secondaryColor: config.secondaryColor || '#a78bfa',
        position: config.position || 'bottom-right',
        botName: config.botName || 'Asistente',
        welcomeMessage: config.welcomeMessage || '¡Hola! ¿En qué puedo ayudarte?',
        botAvatar: config.botAvatar || '🤖',
        govLogoUrl: config.govLogoUrl || null,
        footerLogoUrl: config.footerLogoUrl || null,
        contactEmail: config.contactEmail || null,
        contactWhatsapp: config.contactWhatsapp || null,  // solo dígitos con código de país
        allowUserUploads: !!config.allowUserUploads,  // permite subir un PDF en el chat
        chatUploadMaxMb: config.chatUploadMaxMb || 8,
        orgLogoUrl: config.orgLogoUrl || null,
        suggestedQuestions: Array.isArray(config.suggestedQuestions) ? config.suggestedQuestions.slice(0,3) : [],
        showBranding: config.showBranding !== false,
        apiKey: config.apiKey || null,
      };
      this.sessionId = this._getSessionId();
      this.isOpen = false;
      this.isTyping = false;
      this.messages = [];
      this._injectStyles();
      this._render();
      this._bindEvents();
    }

    _getSessionId() {
      let sid = sessionStorage.getItem('ragbot_session');
      if (!sid) {
        sid = 'sess_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
        sessionStorage.setItem('ragbot_session', sid);
      }
      return sid;
    }

    _injectStyles() {
      if (document.getElementById('ragbot-styles')) return;
      const style = document.createElement('style');
      style.id = 'ragbot-styles';
      style.textContent = CSS.replace(/var\(--rb-color, #6c63ff\)/g, `var(--rb-color, ${this.config.primaryColor})`);
      document.head.appendChild(style);

      // Set CSS vars
      document.documentElement.style.setProperty('--rb-color', this.config.primaryColor);
      document.documentElement.style.setProperty('--rb-color2', this.config.secondaryColor);
      document.documentElement.style.setProperty('--rb-bubble-bg', this._tintColor(this.config.secondaryColor, 0.85));
    }

    // Mezcla un color hex con blanco (amount=1 -> blanco puro) para un tono pastel
    // siempre legible con texto oscuro, sin importar cuán saturado sea el color elegido.
    _tintColor(hexColor, amount = 0.85) {
      let h = (hexColor || '').replace('#', '');
      if (h.length === 3) h = h.split('').map(c => c + c).join('');
      if (!/^[0-9a-fA-F]{6}$/.test(h)) return '#f5f5f8';
      const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
      const mix = c => Math.round(c + (255 - c) * amount).toString(16).padStart(2, '0');
      return `#${mix(r)}${mix(g)}${mix(b)}`;
    }

    _render() {
      const container = document.createElement('div');
      container.id = 'ragbot-container';
      container.innerHTML = `
        <!-- Trigger Button -->
        <button id="ragbot-trigger" class="${this.config.position}" aria-label="Abrir chat">
          <span id="rb-trigger-icon">💬</span>
          <span id="ragbot-badge">1</span>
        </button>

        <!-- Chat Window -->
        <div id="ragbot-window" class="${this.config.position}" role="dialog" aria-label="Chat con ${this._escapeHtml(this.config.botName)}">
          <div id="rb-header">
            ${this._govLogoHtml()}
            ${this._orgLogoHtml()}
            <div id="rb-avatar">${this._avatarHtml(this.config.botAvatar)}</div>
            <div id="rb-header-info">
              <div id="rb-bot-name">${this._escapeHtml(this.config.botName)}</div>
              <div id="rb-status"><span class="rb-dot"></span> En línea</div>
            </div>
            ${this._helpButtonHtml()}
            <button id="rb-close-btn" aria-label="Cerrar">✕</button>
          </div>
          ${this._helpMenuHtml()}
          ${this._contactFormHtml()}

          <div id="rb-messages" role="log" aria-live="polite"></div>

          <div id="rb-input-area">
            ${this.config.allowUserUploads ? `<input type="file" id="rb-file-input" accept="application/pdf" style="display:none">
            <button type="button" id="rb-attach" aria-label="Adjuntar PDF" title="Adjuntar PDF">📎</button>` : ''}
            <textarea id="rb-input" placeholder="Escribe tu pregunta..." rows="1" maxlength="2000"></textarea>
            <button id="rb-send" aria-label="Enviar">
              <svg fill="none" stroke="#fff" stroke-width="2" viewBox="0 0 24 24">
                <line x1="22" y1="2" x2="11" y2="13"></line>
                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
              </svg>
            </button>
          </div>

          ${this._footerHtml()}
        </div>
      `;
      document.body.appendChild(container);
      this.elements = {
        trigger: document.getElementById('ragbot-trigger'),
        window: document.getElementById('ragbot-window'),
        messages: document.getElementById('rb-messages'),
        input: document.getElementById('rb-input'),
        send: document.getElementById('rb-send'),
        badge: document.getElementById('ragbot-badge'),
        triggerIcon: document.getElementById('rb-trigger-icon'),
      };
      this._addWelcomeMessage();
    }

    _addWelcomeMessage() {
      this._appendMessage('bot', this.config.welcomeMessage);
      this._renderSuggestions();
      // Show badge after 2s
      setTimeout(() => {
        this.elements.badge.style.display = 'flex';
      }, 2000);
    }

    _renderSuggestions() {
      if (!this.config.suggestedQuestions.length) return;
      const wrap = document.createElement('div');
      wrap.className = 'rb-suggestions';
      wrap.id = 'rb-suggestions';
      wrap.innerHTML = this.config.suggestedQuestions
        .map(q => `<button type="button" class="rb-suggestion-btn">${this._escapeHtml(q)}</button>`)
        .join('');
      // Al tocar una sugerencia se copia al campo de texto (para editarla o completarla) y NO se envía
      wrap.querySelectorAll('.rb-suggestion-btn').forEach((btn, i) => {
        btn.addEventListener('click', () => {
          this.elements.input.value = this.config.suggestedQuestions[i];
          this.elements.input.style.height = 'auto';
          this.elements.input.style.height = Math.min(this.elements.input.scrollHeight, 100) + 'px';
          this.elements.input.focus();
        });
      });
      this.elements.messages.appendChild(wrap);
      this.elements.messages.scrollTop = this.elements.messages.scrollHeight;
    }

    _bindEvents() {
      this.elements.trigger.addEventListener('click', () => this.toggle());
      document.getElementById('rb-close-btn').addEventListener('click', () => this.close());
      const helpBtn = document.getElementById('rb-help-btn');
      if (helpBtn) {
        const menu = document.getElementById('rb-help-menu');
        helpBtn.addEventListener('click', e => { e.stopPropagation(); menu.classList.toggle('open'); });
        document.addEventListener('click', () => menu.classList.remove('open'));
      }
      document.querySelector('#rb-help-menu .rb-contact-form-btn')?.addEventListener('click', () => this._openContactForm());
      document.getElementById('rb-cf-close')?.addEventListener('click', () => this._closeContactForm());
      document.getElementById('rb-cf-submit')?.addEventListener('click', () => this._submitContactForm());

      this.elements.send.addEventListener('click', () => this._sendMessage());
      this.elements.input.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this._sendMessage(); }
      });

      const attachBtn = document.getElementById('rb-attach');
      if (attachBtn) {
        const fileInput = document.getElementById('rb-file-input');
        attachBtn.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', () => {
          if (fileInput.files[0]) this._uploadPdf(fileInput.files[0]);
          fileInput.value = '';
        });
      }

      // Auto-resize textarea
      this.elements.input.addEventListener('input', () => {
        this.elements.input.style.height = 'auto';
        this.elements.input.style.height = Math.min(this.elements.input.scrollHeight, 100) + 'px';
      });
    }

    toggle() { this.isOpen ? this.close() : this.open(); }

    open() {
      this.isOpen = true;
      this.elements.window.classList.add('open');
      this.elements.triggerIcon.textContent = '✕';
      this.elements.badge.style.display = 'none';
      setTimeout(() => this.elements.input.focus(), 300);
    }

    close() {
      this.isOpen = false;
      this.elements.window.classList.remove('open');
      this.elements.triggerIcon.textContent = '💬';
    }

    async _sendMessage() {
      const text = this.elements.input.value.trim();
      if (!text || this.isTyping) return;

      this.elements.input.value = '';
      this.elements.input.style.height = 'auto';
      this._appendMessage('user', text);
      this._showTyping();
      this.isTyping = true;

      try {
        const headers = { 'Content-Type': 'application/json' };
        if (this.config.apiKey) headers['X-API-Key'] = this.config.apiKey;
        const res = await fetch(`${this.config.apiUrl}/api/v1/chat/${this.config.botId}`, {
          method: 'POST',
          headers,
          body: JSON.stringify({ message: text, session_id: this.sessionId }),
        });

        // Si la respuesta no es JSON válido (ej. una página de error de un proxy por timeout),
        // res.json() tira acá y cae al catch de abajo — ahí NO hay un "detail" curado que
        // mostrar, por eso ese caso usa el mensaje genérico (nunca el error técnico crudo).
        const data = await res.json();
        this._hideTyping();

        if (!res.ok) {
          // Mensaje curado del backend (ej. "no disponible", límite mensual): sí es seguro mostrarlo.
          this._appendMessage('bot', data.detail || 'Error del servidor', [], true, true);
          return;
        }
        this._appendMessage('bot', data.answer, data.sources || [], false, data.suggest_contact);
      } catch(err) {
        this._hideTyping();
        // Fallo de red o respuesta no-JSON (ej. timeout del proxy): mensaje genérico, nunca el
        // texto técnico del error — y se ofrece el contacto humano si el bot lo tiene configurado.
        this._appendMessage('bot', 'Uy, tuve un problema técnico y no pude responder. Probá de nuevo en unos minutos.', [], true, true);
      } finally {
        this.isTyping = false;
      }
    }

    async _uploadPdf(file) {
      if (this.isTyping) return;
      // No confiamos solo en file.type (algunos navegadores/SO lo dejan vacío o distinto para
      // PDFs); la extensión alcanza para el chequeo rápido del cliente, el servidor valida la
      // firma real del archivo.
      if (file.type && file.type !== 'application/pdf' && !/\.pdf$/i.test(file.name)) {
        this._appendMessage('bot', 'Solo se aceptan archivos PDF.', [], true);
        return;
      }
      if (file.size > this.config.chatUploadMaxMb * 1024 * 1024) {
        this._appendMessage('bot', `El archivo supera el límite de ${this.config.chatUploadMaxMb}MB.`, [], true);
        return;
      }

      this._appendMessage('user', `📎 ${file.name}`);
      this._showTyping();
      this.isTyping = true;
      document.getElementById('rb-attach').disabled = true;

      try {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('session_id', this.sessionId);
        const headers = {};
        if (this.config.apiKey) headers['X-API-Key'] = this.config.apiKey;
        const res = await fetch(`${this.config.apiUrl}/api/v1/chat/${this.config.botId}/upload`, {
          method: 'POST', headers, body: formData,
        });
        const data = await res.json();
        this._hideTyping();
        if (!res.ok) throw new Error(data.detail || 'Error al procesar el documento');
        this._appendMessage('bot', data.message);
      } catch(err) {
        this._hideTyping();
        this._appendMessage('bot', `No pude procesar el documento. ${err.message}`, [], true);
      } finally {
        this.isTyping = false;
        const btn = document.getElementById('rb-attach');
        if (btn) btn.disabled = false;
      }
    }

    _appendMessage(role, content, sources = [], isError = false, suggestContact = false) {
      const el = document.createElement('div');
      el.className = `rb-msg ${role}`;

      const time = new Date().toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' });
      const sourcesHtml = sources.length
        ? `<div class="rb-sources">${sources.map(s => `<span class="rb-source-tag">📎 ${this._escapeHtml(s)}</span>`).join('')}</div>`
        : '';
      const contactHtml = suggestContact ? this._contactChipsHtml() : '';

      el.innerHTML = `
        <div class="rb-msg-avatar">${role === 'bot' ? this._avatarHtml(this.config.botAvatar) : '👤'}</div>
        <div>
          <div class="rb-bubble${isError ? ' style="background:#fff0f0;color:#ef4444"' : ''}">${this._renderMessageContent(content)}${sourcesHtml}</div>
          <div class="rb-time">${time}</div>
          ${contactHtml}
        </div>`;

      this.elements.messages.appendChild(el);
      this.elements.messages.scrollTop = this.elements.messages.scrollHeight;
      this.messages.push({ role, content, time });

      // El chip "Formulario" se arma dinámicamente (no existe al bindear _bindEvents).
      el.querySelector('.rb-contact-form-btn')?.addEventListener('click', () => this._openContactForm());
    }

    // Chips de contacto inline, debajo de un mensaje puntual donde el bot no encontró la
    // respuesta (suggest_contact del backend). Vacío si el bot no tiene contacto configurado.
    _contactChipsHtml() {
      if (!this.config.contactEmail && !this.config.contactWhatsapp) return '';
      const items = ['<button type="button" class="rb-contact-chip rb-contact-form-btn">📝 Formulario</button>'];
      if (this.config.contactWhatsapp) {
        items.push(`<a class="rb-contact-chip" href="https://wa.me/${this._escapeHtml(this.config.contactWhatsapp)}" target="_blank" rel="noopener">🟢 WhatsApp</a>`);
      }
      return `<div class="rb-contact-prompt">¿No era lo que buscabas?<div class="rb-contact-chips">${items.join('')}</div></div>`;
    }

    _openContactForm() {
      const menu = document.getElementById('rb-help-menu');
      if (menu) menu.classList.remove('open');
      const form = document.getElementById('rb-contact-form');
      if (!form) return;
      form.classList.add('open');
      document.getElementById('rb-cf-error').classList.remove('show');
      setTimeout(() => document.getElementById('rb-cf-name').focus(), 100);
    }

    _closeContactForm() {
      document.getElementById('rb-contact-form')?.classList.remove('open');
    }

    async _submitContactForm() {
      const name = document.getElementById('rb-cf-name').value.trim();
      const email = document.getElementById('rb-cf-email').value.trim();
      const phone = document.getElementById('rb-cf-phone').value.trim();
      const question = document.getElementById('rb-cf-question').value.trim();
      const errorEl = document.getElementById('rb-cf-error');
      const showError = msg => { errorEl.textContent = msg; errorEl.classList.add('show'); };
      errorEl.classList.remove('show');

      if (!name) return showError('Contanos tu nombre.');
      if (!question) return showError('Contanos tu consulta.');
      if (!email && !phone) return showError('Dejanos un email o un teléfono para poder responderte.');

      const submitBtn = document.getElementById('rb-cf-submit');
      submitBtn.disabled = true;
      submitBtn.textContent = 'Enviando...';
      try {
        const headers = { 'Content-Type': 'application/json' };
        if (this.config.apiKey) headers['X-API-Key'] = this.config.apiKey;
        const res = await fetch(`${this.config.apiUrl}/api/v1/chat/${this.config.botId}/contact-request`, {
          method: 'POST', headers,
          body: JSON.stringify({ name, email: email || null, phone: phone || null, question, session_id: this.sessionId }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'No se pudo enviar la consulta');

        this._closeContactForm();
        ['rb-cf-name', 'rb-cf-email', 'rb-cf-phone', 'rb-cf-question'].forEach(id => { document.getElementById(id).value = ''; });
        this._appendMessage('bot', data.message);
      } catch(err) {
        showError(err.message);
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Enviar consulta';
      }
    }

    _showTyping() {
      const el = document.createElement('div');
      el.className = 'rb-msg bot';
      el.id = 'rb-typing-indicator';
      el.innerHTML = `
        <div class="rb-msg-avatar">${this._avatarHtml(this.config.botAvatar)}</div>
        <div class="rb-typing"><span></span><span></span><span></span></div>`;
      this.elements.messages.appendChild(el);
      this.elements.messages.scrollTop = this.elements.messages.scrollHeight;
    }

    _hideTyping() {
      document.getElementById('rb-typing-indicator')?.remove();
    }

    _avatarHtml(value) {
      if (!value) return '🤖';
      if (/^https?:\/\//.test(value) || value.startsWith('/')) {
        const src = value.startsWith('/') ? this.config.apiUrl + value : value;
        return `<img src="${this._escapeHtml(src)}" style="width:100%;height:100%;border-radius:50%;object-fit:cover;display:block">`;
      }
      return this._escapeHtml(value);
    }

    _govLogoHtml() {
      if (!this.config.govLogoUrl) return '';
      const url = this.config.govLogoUrl;
      const src = url.startsWith('/') ? this.config.apiUrl + url : url;
      return `<img id="rb-gov-logo" src="${this._escapeHtml(src)}" alt="Gobierno de Salta">`;
    }

    _helpButtonHtml() {
      if (!this.config.contactEmail && !this.config.contactWhatsapp) return '';
      return '<button type="button" id="rb-help-btn" aria-label="Hablar con una persona" title="Hablar con una persona">🆘</button>';
    }

    _helpMenuHtml() {
      if (!this.config.contactEmail && !this.config.contactWhatsapp) return '';
      const items = ['<button type="button" class="rb-contact-form-btn">📝 Completar formulario</button>'];
      if (this.config.contactWhatsapp) {
        items.push(`<a href="https://wa.me/${this._escapeHtml(this.config.contactWhatsapp)}" target="_blank" rel="noopener">🟢 Escribir por WhatsApp</a>`);
      }
      return `<div id="rb-help-menu">${items.join('')}</div>`;
    }

    // Panel del formulario "hablar con una persona" (overlay dentro de la ventana del chat).
    _contactFormHtml() {
      if (!this.config.contactEmail && !this.config.contactWhatsapp) return '';
      const waLink = this.config.contactWhatsapp
        ? `<a class="rb-cf-wa" href="https://wa.me/${this._escapeHtml(this.config.contactWhatsapp)}" target="_blank" rel="noopener">🟢 O escribinos directo por WhatsApp</a>`
        : '';
      return `
        <div id="rb-contact-form">
          <div class="rb-cf-header">
            <span>Hablar con una persona</span>
            <button type="button" id="rb-cf-close" aria-label="Cerrar">✕</button>
          </div>
          <div class="rb-cf-body">
            <label for="rb-cf-name">Nombre</label>
            <input type="text" id="rb-cf-name" maxlength="200">
            <label for="rb-cf-email">Email</label>
            <input type="email" id="rb-cf-email">
            <label for="rb-cf-phone">Teléfono</label>
            <input type="tel" id="rb-cf-phone" placeholder="Con código de país, ej: 5493871234567">
            <label for="rb-cf-question">Tu consulta</label>
            <textarea id="rb-cf-question" rows="4" maxlength="2000"></textarea>
            <div class="rb-cf-hint">Dejanos un email o un teléfono para poder responderte.</div>
            <div class="rb-cf-error" id="rb-cf-error"></div>
            <button type="button" class="rb-cf-submit" id="rb-cf-submit">Enviar consulta</button>
            ${waLink}
          </div>
        </div>`;
    }

    // Pie del chat: logo de Modernización si está cargado; si no, el "Powered by" (si showBranding)
    _footerHtml() {
      const url = this.config.footerLogoUrl;
      if (url) {
        const src = url.startsWith('/') ? this.config.apiUrl + url : url;
        return `<div id="rb-footer" class="rb-footer-logo"><img id="rb-footer-logo" src="${this._escapeHtml(src)}" alt="Modernización"></div>`;
      }
      return this.config.showBranding ? '<div id="rb-footer"><a href="#" target="_blank">Powered by RAGBot</a></div>' : '';
    }

    _orgLogoHtml() {
      if (!this.config.orgLogoUrl) return '';
      const url = this.config.orgLogoUrl;
      const src = url.startsWith('/') ? this.config.apiUrl + url : url;
      return `<img id="rb-org-logo" src="${this._escapeHtml(src)}" alt="Logo del organismo">`;
    }

    _escapeHtml(str) {
      return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
               .replace(/"/g,'&quot;').replace(/\n/g,'<br>');
    }

    // Texto del bot ya escapado + enlaces markdown [texto](url) convertidos a <a> (para los
    // recursos descargables que arma el backend). Corre DESPUÉS de escapar, así solo linkea
    // texto ya seguro; una URL relativa ("/static/...") se resuelve con apiUrl, igual que
    // bot_avatar_url — necesario para que el link funcione embebido en un sitio de terceros.
    _renderMessageContent(content) {
      const escaped = this._escapeHtml(content);
      return escaped.replace(/\[([^\[\]]+)\]\((\/[^\s()]+|https?:\/\/[^\s()]+)\)/g, (m, text, url) => {
        const href = url.startsWith('/') ? this.config.apiUrl + url : url;
        return `<a href="${href}" target="_blank" rel="noopener">${text}</a>`;
      });
    }
  }

  // ─── Expose API ────────────────────────────────────────────
  window.RAGBot = {
    init: (config) => {
      if (window._ragbotInstance) window._ragbotInstance = null;
      window._ragbotInstance = new RAGBotWidget(config);
      return window._ragbotInstance;
    },
    open: () => window._ragbotInstance?.open(),
    close: () => window._ragbotInstance?.close(),
    toggle: () => window._ragbotInstance?.toggle(),
  };

})(window);
