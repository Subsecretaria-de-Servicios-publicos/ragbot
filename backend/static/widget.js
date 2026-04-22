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
      background: var(--rb-color, #6c63ff);
      padding: 14px 16px;
      display: flex; align-items: center; gap: 10px;
      flex-shrink: 0;
    }
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
      background: #f5f5f8;
      border-bottom-left-radius: 4px;
      color: #1a1a2e;
    }
    .rb-msg.user .rb-bubble {
      background: var(--rb-color, #6c63ff);
      color: #fff;
      border-bottom-right-radius: 4px;
    }

    .rb-sources {
      margin-top: 6px; font-size: 11px; color: #888;
      display: flex; flex-wrap: wrap; gap: 4px;
    }
    .rb-source-tag {
      background: #ebebf5; color: #666; padding: 2px 8px;
      border-radius: 20px; font-size: 11px;
    }

    .rb-time { font-size: 10px; color: #bbb; margin-top: 4px; text-align: right; }

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

    #rb-footer { padding: 6px 12px 10px; text-align: center; }
    #rb-footer a { font-size: 10px; color: #ccc; text-decoration: none; }
    #rb-footer a:hover { color: #999; }

    /* Welcome card */
    .rb-welcome {
      background: linear-gradient(135deg, var(--rb-color, #6c63ff), #a78bfa);
      border-radius: 12px; padding: 16px; color: #fff; margin-bottom: 4px;
    }
    .rb-welcome-title { font-size: 15px; font-weight: 600; margin-bottom: 4px; }
    .rb-welcome-sub { font-size: 12px; opacity: 0.85; }
  `;

  // ─── RAGBot Widget Class ────────────────────────────────────
  class RAGBotWidget {
    constructor(config) {
      this.config = {
        botId: config.botId,
        apiUrl: (config.apiUrl || 'http://localhost:8000').replace(/\/$/, ''),
        primaryColor: config.primaryColor || '#6c63ff',
        position: config.position || 'bottom-right',
        botName: config.botName || 'Asistente',
        welcomeMessage: config.welcomeMessage || '¡Hola! ¿En qué puedo ayudarte?',
        botAvatar: config.botAvatar || '🤖',
        showBranding: config.showBranding !== false,
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

      // Set CSS var
      document.documentElement.style.setProperty('--rb-color', this.config.primaryColor);
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
        <div id="ragbot-window" class="${this.config.position}" role="dialog" aria-label="Chat con ${this.config.botName}">
          <div id="rb-header">
            <div id="rb-avatar">${this.config.botAvatar}</div>
            <div id="rb-header-info">
              <div id="rb-bot-name">${this.config.botName}</div>
              <div id="rb-status"><span class="rb-dot"></span> En línea</div>
            </div>
            <button id="rb-close-btn" aria-label="Cerrar">✕</button>
          </div>

          <div id="rb-messages" role="log" aria-live="polite"></div>

          <div id="rb-input-area">
            <textarea id="rb-input" placeholder="Escribe tu pregunta..." rows="1" maxlength="2000"></textarea>
            <button id="rb-send" aria-label="Enviar">
              <svg fill="none" stroke="#fff" stroke-width="2" viewBox="0 0 24 24">
                <line x1="22" y1="2" x2="11" y2="13"></line>
                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
              </svg>
            </button>
          </div>

          ${this.config.showBranding ? '<div id="rb-footer"><a href="#" target="_blank">Powered by RAGBot</a></div>' : ''}
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
      const msgEl = document.createElement('div');
      msgEl.innerHTML = `
        <div class="rb-welcome">
          <div class="rb-welcome-title">${this.config.botName}</div>
          <div class="rb-welcome-sub">Estoy aquí para ayudarte</div>
        </div>`;
      this.elements.messages.appendChild(msgEl);
      this._appendMessage('bot', this.config.welcomeMessage);
      // Show badge after 2s
      setTimeout(() => {
        this.elements.badge.style.display = 'flex';
      }, 2000);
    }

    _bindEvents() {
      this.elements.trigger.addEventListener('click', () => this.toggle());
      document.getElementById('rb-close-btn').addEventListener('click', () => this.close());

      this.elements.send.addEventListener('click', () => this._sendMessage());
      this.elements.input.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this._sendMessage(); }
      });

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
        const res = await fetch(`${this.config.apiUrl}/api/v1/chat/${this.config.botId}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text, session_id: this.sessionId }),
        });

        const data = await res.json();
        this._hideTyping();

        if (!res.ok) throw new Error(data.detail || 'Error del servidor');

        this._appendMessage('bot', data.answer, data.sources || []);
      } catch(err) {
        this._hideTyping();
        this._appendMessage('bot', `Lo siento, ocurrió un error. ${err.message}`, [], true);
      } finally {
        this.isTyping = false;
      }
    }

    _appendMessage(role, content, sources = [], isError = false) {
      const el = document.createElement('div');
      el.className = `rb-msg ${role}`;

      const time = new Date().toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' });
      const sourcesHtml = sources.length
        ? `<div class="rb-sources">${sources.map(s => `<span class="rb-source-tag">📎 ${s}</span>`).join('')}</div>`
        : '';

      el.innerHTML = `
        <div class="rb-msg-avatar">${role === 'bot' ? this.config.botAvatar : '👤'}</div>
        <div>
          <div class="rb-bubble${isError ? ' style="background:#fff0f0;color:#ef4444"' : ''}">${this._escapeHtml(content)}${sourcesHtml}</div>
          <div class="rb-time">${time}</div>
        </div>`;

      this.elements.messages.appendChild(el);
      this.elements.messages.scrollTop = this.elements.messages.scrollHeight;
      this.messages.push({ role, content, time });
    }

    _showTyping() {
      const el = document.createElement('div');
      el.className = 'rb-msg bot';
      el.id = 'rb-typing-indicator';
      el.innerHTML = `
        <div class="rb-msg-avatar">${this.config.botAvatar}</div>
        <div class="rb-typing"><span></span><span></span><span></span></div>`;
      this.elements.messages.appendChild(el);
      this.elements.messages.scrollTop = this.elements.messages.scrollHeight;
    }

    _hideTyping() {
      document.getElementById('rb-typing-indicator')?.remove();
    }

    _escapeHtml(str) {
      return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
               .replace(/"/g,'&quot;').replace(/\n/g,'<br>');
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
