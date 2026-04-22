/**
 * DuoNet Chat Core Module
 * Central coordination, WebSocket management, encryption/decryption
 * Supports dual-key mode during key rotation
 */

class DuoNetCore {
    constructor(contactId, token, currentUserId) {
        this.contactId = contactId;
        this.token = token;
        this.currentUserId = currentUserId;
        this.dialogId = this.currentUserId < this.contactId
            ? `${this.currentUserId}:${this.contactId}`
            : `${this.contactId}:${this.currentUserId}`;

        this.ws = null;
        this.crypto = null;
        this.rotation = null;
        this.messages = null;
        this.system = null;

        this.sessionKeyHex = null;
        // Dual-key mode support during rotation
        this.activeKeys = {
            old: null,   // previous key (still valid for decrypting old messages)
            new: null    // new key (after CONFIRM)
        };
        this.currentPhrase = null;
        this.phraseKnown = false;
        this.wsReady = false;

        this._initialized = false;
        this._typingTimeout = null;
        this.pendingMessageIds = new Set();
    }

    async init() {
        this.crypto = new DuoNetCrypto();

        const keyLoaded = await this.loadSessionKey();
        if (!keyLoaded) {
            DuoNetUI.showErrorInElement(
                document.getElementById('messages'),
                'Dialog not established. Please send an invite first.'
            );
            return false;
        }

        await this.loadPhraseStatus();

        // Initialize submodules
        this.messages = new DuoNetMessages(this);
        this.system = new DuoNetSystemHandler(this);
        this.rotation = new DuoNetRotation(this);

        this.rotation.init();

        // Connect WebSocket first to receive messages
        this.connectWebSocket();

        // Load messages from DB
        await this.messages.loadMessages();

        // After messages are loaded, restore rotation state from them
        await this.rotation.restoreStateFromMessages();

        // УДАЛИТЬ ЭТОТ БЛОК:
        // setTimeout(async () => {
        //     console.log('[Core] Retry restoring rotation state after 3s delay');
        //     await this.messages.loadMessages(false);
        //     await this.rotation.restoreStateFromMessages();
        // }, 3000);

        this.setupEventListeners();
        this._initialized = true;
        return true;
    }

    async loadSessionKey() {
        const storedKey = DuoNetCrypto.getStoredSessionKey(this.dialogId);
        if (storedKey) {
            this.sessionKeyHex = storedKey;
            this.activeKeys.old = storedKey;
            return true;
        }
        try {
            const response = await fetch(`/api/web/dialog/${this.contactId}/session-key`);
            const result = await response.json();
            if (result.success && result.data.session_key) {
                this.sessionKeyHex = result.data.session_key;
                this.activeKeys.old = result.data.session_key;
                DuoNetCrypto.storeSessionKey(this.dialogId, this.sessionKeyHex);
                return true;
            }
        } catch (error) {
            console.error('Failed to load session key:', error);
        }
        return false;
    }

    async loadPhraseStatus() {
        try {
            const response = await fetch(`/api/web/chat/${this.contactId}/phrase`);
            const result = await response.json();
            if (result.success) {
                this.phraseKnown = result.data.phrase_known;
                const storedPhrase = DuoNetCrypto.getStoredPhrase(this.contactId);
                if (storedPhrase) {
                    this.currentPhrase = storedPhrase;
                }
                DuoNetUI.updatePhraseUI(this.phraseKnown, !!this.currentPhrase);
            }
        } catch (error) {
            console.error('Failed to load phrase status:', error);
        }
    }

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        const wsUrl = `${protocol}//${host}/ws?token=${encodeURIComponent(this.token)}&contact=${encodeURIComponent(this.contactId)}`;

        this.ws = new DuoNetChatWebSocket(wsUrl, this.contactId, {
            onMessage: (data) => this.handleMessage(data),
            onStatusResponse: (data) => DuoNetUI.updateOnlineStatus(data.online === true),
            onTyping: (data) => this.handleTyping(data),
            onOpen: () => {
                console.log('✅ WebSocket opened and ready');
                this.wsReady = true;
                const sendBtn = document.getElementById('sendBtn');
                const msgInput = document.getElementById('messageInput');
                if (sendBtn) sendBtn.disabled = false;
                if (msgInput) msgInput.disabled = false;
                if (this.ws) this.ws.sendStatus(true);
            },
            onClose: () => {
                console.log('WebSocket closed');
                this.wsReady = false;
                const sendBtn = document.getElementById('sendBtn');
                const msgInput = document.getElementById('messageInput');
                if (sendBtn) sendBtn.disabled = true;
                if (msgInput) msgInput.disabled = true;
                DuoNetUI.updateOnlineStatus(false);
            },
            onError: (error) => {
                if (error && error.code === 'unknown_type') return;
                DuoNetUI.showToast('WebSocket connection error', 'error');
            }
        });
        this.ws.connect().catch(console.error);
    }

    async _decryptWithKey(ciphertextHex, keyHex, fromId, toId, phrase) {
        try {
            const decrypted = await this.crypto.decryptLRP(
                ciphertextHex, keyHex, fromId, toId, phrase
            );
            return decrypted;
        } catch (e) {
            return null;
        }
    }

    async decryptMessage(ciphertextHex, keyHex, fromId, toId, phrase) {
        // 1. Try new key (transition period)
        if (this.activeKeys.new) {
            const decrypted = await this._decryptWithKey(ciphertextHex, this.activeKeys.new, fromId, toId, phrase);
            if (decrypted !== null) return decrypted;
        }
        // 2. Try old key (transition period)
        if (this.activeKeys.old) {
            const decrypted = await this._decryptWithKey(ciphertextHex, this.activeKeys.old, fromId, toId, phrase);
            if (decrypted !== null) return decrypted;
        }
        // 3. Fallback: try provided key from message
        const keyToTry = keyHex || this.sessionKeyHex;
        if (keyToTry) {
            return await this._decryptWithKey(ciphertextHex, keyToTry, fromId, toId, phrase);
        }
        // 4. If nothing worked, return null
        return null;
    }

    async handleMessage(data) {
        if (data === "pong") return;
        let msgData = data;
        if (typeof msgData === 'string') {
            try {
                msgData = JSON.parse(msgData);
            } catch (e) {
                return;
            }
        }
        if (msgData.type === 'message') {
            const content = msgData.data;
            // Проверка на дубликат в DOM
            if (document.querySelector(`[data-message-id="${content.message_id}"]`)) return;
            if (this.pendingMessageIds.has(content.message_id)) {
                this.pendingMessageIds.delete(content.message_id);
                return;
            }
            let decrypted = null;
            if (content.encrypted && content.session_key) {
                const phrase = content.has_phrase ? this.currentPhrase : null;
                decrypted = await this.decryptMessage(
                    content.encrypted, content.session_key,
                    content.from, this.currentUserId, phrase
                );
            }
            // Отслеживаем сообщение в переходном окне
            this._trackTransitionMessage();

            // ✅ СОЗДАЁМ ОБЪЕКТ СООБЩЕНИЯ
            const messageObj = {
                id: content.message_id,
                from: content.from,
                from_id: content.from,
                encrypted: content.encrypted,
                session_key: content.session_key,
                timestamp: content.timestamp || Math.floor(Date.now() / 1000),
                has_phrase: content.has_phrase,
                decrypted_text: decrypted,
                is_own: content.from === this.currentUserId,
                is_system: 0,
                delivered: true,
                read: false
            };
            // Проверяем, не системное ли оно
            if (decrypted && decrypted.includes('"__type":"system"')) {
                await this.system.handle(decrypted, content);
                return;
            }
            // Добавляем в UI и в массив
            this.messages.addToUI(messageObj);
            // Отмечаем как прочитанное, если окно активно
            if (document.hasFocus()) {
                await this.markMessageRead(content.message_id);
            }
        }
    }

    handleTyping(data) {
        const typingDiv = document.getElementById('typingIndicator');
        if (typingDiv) {
            if (data.is_typing) {
                typingDiv.textContent = `${data.from} is typing...`;
                setTimeout(() => {
                    if (typingDiv.textContent === `${data.from} is typing...`) {
                        typingDiv.textContent = '';
                    }
                }, 3000);
            } else {
                typingDiv.textContent = '';
            }
        }
    }

    async sendMessage(text) {
        if (!text || !this.sessionKeyHex) return false;

        if (!this.ws || !this.ws.isConnected() || !this.wsReady) {
            console.log('WebSocket not ready, waiting...');
            await new Promise(resolve => setTimeout(resolve, 2000));
            if (!this.ws || !this.ws.isConnected() || !this.wsReady) {
                DuoNetUI.showToast('Connection not ready. Please wait.', 'error');
                return false;
            }
        }

        const messageId = DuoNetCrypto.generateMessageId();
        const hasPhrase = this.currentPhrase !== null;
        const timestamp = Math.floor(Date.now() / 1000);

        this.pendingMessageIds.add(messageId);

        try {
            const isSystemMessage = text.includes('"__type":"system"');

            let actualPhrase = hasPhrase ? this.currentPhrase : null;
            if (isSystemMessage) {
                actualPhrase = null;
            }

            const encrypted = await this.crypto.encryptLRP(
                text, this.sessionKeyHex, this.currentUserId,
                this.contactId, actualPhrase
            );

            if (isSystemMessage) {
                try {
                    const parsed = JSON.parse(text);
                    if (parsed.__type === 'system') {
                        this.system.addToUI({
                            id: messageId,
                            from_id: this.currentUserId,
                            timestamp: timestamp,
                            system_type: parsed.subtype?.toUpperCase(),
                            system_data: parsed,
                            rotation_id: parsed.rotation_id,
                            expires_at: parsed.expires_at,
                            eph_public_key: parsed.eph_public_key
                        });
                    }
                } catch(e) {}
            } else {
                this.messages.addToUI({
                    id: messageId,
                    from: this.currentUserId,
                    encrypted: encrypted.ciphertext,
                    session_key: this.sessionKeyHex,
                    timestamp: timestamp,
                    has_phrase: hasPhrase,
                    decrypted_text: text,
                    is_own: true
                });
            }

            if (this.ws && this.ws.isConnected() && this.wsReady) {
                const sendHasPhrase = isSystemMessage ? false : hasPhrase;
                this.ws.sendChatMessage(messageId, encrypted.ciphertext, this.sessionKeyHex, sendHasPhrase, text);
            }

            setTimeout(() => this.pendingMessageIds.delete(messageId), 5000);
            return true;
        } catch (error) {
            console.error('Encryption error:', error);
            this.pendingMessageIds.delete(messageId);
            return false;
        }
    }

    async markMessageRead(messageId) {
        try {
            await fetch('/api/messages/read', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${this.token}` },
                body: JSON.stringify({ message_id: messageId })
            });
        } catch (error) {
            console.error('Failed to mark message as read:', error);
        }
    }

    setupEventListeners() {
        const sendBtn = document.getElementById('sendBtn');
        const msgInput = document.getElementById('messageInput');

        if (sendBtn) {
            sendBtn.onclick = () => {
                const input = document.getElementById('messageInput');
                if (input.value.trim()) {
                    this.sendMessage(input.value.trim());
                    input.value = '';
                }
            };
        }

        if (msgInput) {
            msgInput.onkeypress = (e) => {
                if (e.key === 'Enter') {
                    if (msgInput.value.trim()) {
                        this.sendMessage(msgInput.value.trim());
                        msgInput.value = '';
                    }
                }
            };
            msgInput.oninput = () => {
                if (this.ws && this.ws.isConnected() && this.wsReady) {
                    this.ws.sendTyping(this.contactId, true);
                    if (this._typingTimeout) clearTimeout(this._typingTimeout);
                    this._typingTimeout = setTimeout(() => {
                        if (this.ws && this.ws.isConnected() && this.wsReady) {
                            this.ws.sendTyping(this.contactId, false);
                        }
                    }, 1000);
                }
            };
        }

        const backBtn = document.querySelector('.back-button');
        if (backBtn) backBtn.onclick = () => window.location.href = '/contacts';
    }

    async refreshMessagesDecryption() {
        console.log('[Core] Refreshing message decryption...');

        const messageElements = document.querySelectorAll('.message[data-message-id]');
        let refreshedCount = 0;

        for (const el of messageElements) {
            const messageId = el.getAttribute('data-message-id');
            const msg = this.messages?.messages?.find(m => m.id === messageId);

            if (msg && !msg.decrypted_text && !msg.is_system) {
                const phrase = msg.has_phrase ? this.currentPhrase : null;
                const decrypted = await this.decryptMessage(
                    msg.encrypted, msg.session_key,
                    msg.from_id, this.currentUserId, phrase
                );

                if (decrypted && decrypted !== msg.decrypted_text) {
                    msg.decrypted_text = decrypted;

                    // Update UI
                    const textSpan = el.querySelector('.message-text');
                    if (textSpan) {
                        textSpan.textContent = decrypted;
                    } else {
                        const contentDiv = el.querySelector('div:first-child');
                        if (contentDiv) {
                            const currentHtml = contentDiv.innerHTML;
                            const newHtml = currentHtml.replace(/🔒 \[.*?\]/, decrypted);
                            contentDiv.innerHTML = newHtml;
                        }
                    }
                    el.classList.remove('message-hidden');
                    refreshedCount++;
                }
            }
        }

        if (refreshedCount > 0) {
            console.log(`[Core] Refreshed ${refreshedCount} messages`);
            DuoNetUI.showToast(`🔓 ${refreshedCount} messages decrypted`, 'success');
        }
    }

    /**
    * Called after each message to track transition window
    */
    _trackTransitionMessage() {
        if (this.isInTransition && this.rotation) {
            this.transitionMsgCounter = (this.transitionMsgCounter || 0) + 1;
            this.rotation._cleanupTransitionWindow();
        }
    }

    destroy() {
        if (this.ws) this.ws.close();
        if (this.rotation) this.rotation.destroy();
        if (this._typingTimeout) clearTimeout(this._typingTimeout);
    }
}

window.DuoNetCore = DuoNetCore;
