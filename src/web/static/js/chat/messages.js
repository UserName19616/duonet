/**
 * DuoNet Messages Module
 * Loading, displaying, and managing message history
 */

class DuoNetMessages {
    constructor(core) {
        this.core = core;
        this.messages = [];
        this.currentOffset = 0;
        this.hasMoreMessages = true;
        this.isLoadingMore = false;
        // Хранилище обработанных rotation_id (для исключения дублей)
        this.processed = new Set();
        // Карта статусов ротации для загруженных сообщений
        this._rotationStatus = new Map();
    }

    // Порядок статусов (чем больше число, тем "позже" статус)
    static _statusOrder = {
        'REQUEST': 1,
        'ACCEPT': 2,
        'CONFIRM': 3,
        'COMPLETE': 4,
        'REJECT': 5,
        'TIMEOUT': 6
    };

    /**
     * Определяет, является ли новый статус более поздним, чем старый
     */
    _isLaterStatus(newStatus, oldStatus) {
        const newOrder = DuoNetMessages._statusOrder[newStatus] || 0;
        const oldOrder = DuoNetMessages._statusOrder[oldStatus] || 0;
        return newOrder > oldOrder;
    }

    /**
     * Анализирует загруженные сообщения и определяет статус каждого rotation_id
     */
    _analyzeRotationStatus() {
        const tempStatus = new Map();

        for (const msg of this.messages) {
            if (!msg.is_system) continue;

            let rotationId = null;
            let rawType = null;

            if (msg.system_data) {
                try {
                    const data = typeof msg.system_data === 'string'
                        ? JSON.parse(msg.system_data)
                        : msg.system_data;
                    rotationId = data.rotation_id;
                    rawType = msg.system_type || data.subtype;
                } catch (e) {
                    continue;
                }
            }

            if (!rotationId || !rawType) continue;

            let normalizedType = null;
            const rawUpper = rawType.toUpperCase();

            if (rawUpper === 'REQUEST' || rawUpper === 'ROTATION_REQUEST' || rawType === 'rotation_request') {
                normalizedType = 'REQUEST';
            } else if (rawUpper === 'ACCEPT' || rawUpper === 'ROTATION_ACCEPT' || rawType === 'rotation_accept') {
                normalizedType = 'ACCEPT';
            } else if (rawUpper === 'CONFIRM' || rawUpper === 'ROTATION_CONFIRM' || rawType === 'rotation_confirm') {
                normalizedType = 'CONFIRM';
            } else if (rawUpper === 'COMPLETE' || rawUpper === 'ROTATION_COMPLETE' || rawType === 'rotation_complete') {
                normalizedType = 'COMPLETE';
            } else if (rawUpper === 'REJECT' || rawUpper === 'ROTATION_REJECT' || rawType === 'rotation_reject') {
                normalizedType = 'REJECT';
            } else if (rawUpper === 'TIMEOUT' || rawUpper === 'ROTATION_TIMEOUT' || rawType === 'rotation_timeout') {
                normalizedType = 'TIMEOUT';
            }

            if (!normalizedType) continue;

            if (!tempStatus.has(rotationId)) {
                tempStatus.set(rotationId, {
                    status: normalizedType,
                    messageId: msg.id,
                    timestamp: msg.timestamp
                });
            } else {
                const existing = tempStatus.get(rotationId);
                if (this._isLaterStatus(normalizedType, existing.status)) {
                    existing.status = normalizedType;
                    existing.messageId = msg.id;
                    existing.timestamp = msg.timestamp;
                }
            }
        }

        this.processed.clear();
        for (const [rotationId, info] of tempStatus) {
            if (info.status !== 'REQUEST') {
                this.processed.add(`${rotationId}_${info.status}`);
            }
        }

        this._rotationStatus = tempStatus;
    }

    isRotationResolved(rotationId) {
        if (!rotationId) return false;

        for (const status of ['ACCEPT', 'REJECT', 'COMPLETE', 'TIMEOUT', 'CONFIRM']) {
            if (this.processed.has(`${rotationId}_${status}`)) {
                return true;
            }
        }

        const info = this._rotationStatus.get(rotationId);
        if (info && info.status !== 'REQUEST') {
            return true;
        }

        return false;
    }

    getRotationStatus(rotationId) {
        const info = this._rotationStatus.get(rotationId);
        return info ? info.status : null;
    }

    async loadMessages(reset = true) {
        if (this.isLoadingMore) return;
        this.isLoadingMore = true;

        if (reset) {
            this.currentOffset = 0;
            this.hasMoreMessages = true;
            this.messages = [];
            this.processed.clear();
            this._rotationStatus.clear();
            DuoNetUI.clearElement(document.getElementById('messages'));
            DuoNetUI.showLoading(document.getElementById('messages'), 'Loading messages...');
        }

        try {
            const response = await fetch(
                `/api/web/messages/${this.core.contactId}?limit=50&offset=${this.currentOffset}`
            );
            const result = await response.json();

            if (result.success && result.data && result.data.messages) {
                const messages = result.data.messages;
                if (messages.length === 0) {
                    this.hasMoreMessages = false;
                    if (reset) {
                        const div = document.getElementById('messages');
                        if (div) {
                            div.innerHTML = '<div class="loading">✨ No messages yet. Send your first message!</div>';
                        }
                    }
                    return;
                }

                if (reset) {
                    DuoNetUI.clearElement(document.getElementById('messages'));
                }

                messages.sort((a, b) => a.timestamp - b.timestamp);
                this.currentOffset += messages.length;
                this.hasMoreMessages = messages.length === 50;

                const newMessages = [];

                for (const msg of messages) {
                    let decrypted = null;
                    let isSystem = msg.is_system === 1;
                    let systemType = msg.system_type;
                    let systemData = msg.system_data;
                    let rotationId = null;

                    if (isSystem && systemData) {
                        try {
                            const parsed = typeof systemData === 'string'
                                ? JSON.parse(systemData)
                                : systemData;
                            rotationId = parsed.rotation_id;
                            if (systemType === 'rotation_request') systemType = 'REQUEST';
                            if (systemType === 'rotation_accept') systemType = 'ACCEPT';
                            if (systemType === 'rotation_confirm') systemType = 'CONFIRM';
                            if (systemType === 'rotation_complete') systemType = 'COMPLETE';
                            if (systemType === 'rotation_reject') systemType = 'REJECT';
                            if (systemType === 'rotation_timeout') systemType = 'TIMEOUT';
                        } catch (e) {}
                    }

                    if (!isSystem && msg.session_key) {
                        const phrase = msg.has_phrase ? this.core.currentPhrase : null;
                        decrypted = await this.core.crypto.decrypt(
                            msg.encrypted, msg.session_key,
                            msg.from_id, msg.to_id, phrase
                        );

                        if (decrypted && decrypted.includes('"__type":"system"')) {
                            try {
                                const parsed = JSON.parse(decrypted);
                                if (parsed.__type === 'system') {
                                    isSystem = true;
                                    systemType = parsed.subtype?.toUpperCase();
                                    rotationId = parsed.rotation_id;
                                    systemData = parsed;
                                }
                            } catch (e) {}
                        }
                    }

                    const messageObj = {
                        id: msg.id,
                        from: msg.from_id,
                        from_id: msg.from_id,
                        encrypted: msg.encrypted,
                        session_key: msg.session_key,
                        timestamp: msg.timestamp,
                        has_phrase: msg.has_phrase,
                        delivered: msg.delivered,
                        read: msg.read,
                        decrypted_text: decrypted,
                        is_own: msg.from_id === this.core.currentUserId,
                        is_system: isSystem ? 1 : 0,
                        system_type: systemType,
                        system_data: systemData,
                        rotation_id: rotationId
                    };

                    newMessages.push(messageObj);
                    this.messages.push(messageObj);
                }

                this._analyzeRotationStatus();

                for (const msg of newMessages) {
                    this.addToUI(msg);
                }
            }
        } catch (error) {
            console.error('Failed to load messages:', error);
            DuoNetUI.showErrorInElement(document.getElementById('messages'), error.message);
        } finally {
            this.isLoadingMore = false;
        }
    }

    addToUI(msg) {
        const messagesDiv = document.getElementById('messages');
        if (!messagesDiv) return;

        if (document.querySelector(`[data-message-id="${msg.id}"]`)) return;

        const existingInArray = this.messages.some(m => m.id === msg.id);
        if (!existingInArray) {
            this.messages.push(msg);
        }
        // ====================================

        let needsPhrase = false;
        let displayText = msg.decrypted_text;

        const isSystem = msg.is_system === 1 || (msg.decrypted_text && msg.decrypted_text.includes('"__type":"system"'));

        if (isSystem) {
            if (this.core.system) {
                this.core.system.addToUI({
                    id: msg.id,
                    from_id: msg.from,
                    timestamp: msg.timestamp,
                    system_type: msg.system_type,
                    system_data: msg.system_data,
                    rotation_id: msg.rotation_id,
                    expires_at: msg.system_data?.expires_at
                });
            }
            return;
        }

        if (!displayText && msg.has_phrase && !this.core.currentPhrase) {
            needsPhrase = true;
            displayText = '🔒 [Requires secret phrase]';
        } else if (!displayText) {
            displayText = '🔒 [Encrypted message]';
        }

        const element = DuoNetUI.createMessageElement(
            msg, msg.is_own, displayText, needsPhrase, this.core.currentPhrase
        );
        element.setAttribute('data-message-id', msg.id);
        element.setAttribute('data-timestamp', msg.timestamp);
        element.setAttribute('data-encrypted', msg.encrypted);
        element.setAttribute('data-session-key', msg.session_key);
        element.setAttribute('data-has-phrase', msg.has_phrase);

        element.onclick = () => this.showDetails(msg, displayText);

        let inserted = false;
        const existingMessages = messagesDiv.querySelectorAll('.message, .system-message');
        for (let i = 0; i < existingMessages.length; i++) {
            const existingTimestamp = parseInt(existingMessages[i].getAttribute('data-timestamp'));
            if (msg.timestamp < existingTimestamp) {
                messagesDiv.insertBefore(element, existingMessages[i]);
                inserted = true;
                break;
            }
        }
        if (!inserted) {
            messagesDiv.appendChild(element);
        }

        const isNearBottom = messagesDiv.scrollHeight - messagesDiv.scrollTop - messagesDiv.clientHeight < 100;
        if (isNearBottom || msg.is_own) {
            DuoNetUI.scrollToBottom(messagesDiv, false);
        }
    }

    async showDetails(msg, displayText) {
        // Используем session_key ИЗ СООБЩЕНИЯ, а не из core!
        const sessionKeyHex = msg.session_key || 'Not available';

        const detailsDiv = document.getElementById('messageDetails');
        if (!detailsDiv) return;

        let keyIndex = '?';
        let keyIndexDisplay = 'Not available';
        let poolDisplay = '';

        if (msg.encrypted && msg.encrypted.length >= 2) {
            try {
                const firstByteHex = msg.encrypted.substring(0, 2);
                keyIndex = parseInt(firstByteHex, 16);
                if (!isNaN(keyIndex) && keyIndex >= 0 && keyIndex <= 15) {
                    keyIndexDisplay = `K${keyIndex} (0x${firstByteHex})`;
                    poolDisplay = `
                        <div class="key-pool-visualization" style="margin-top: 8px;">
                            <strong>🎲 LRP Key Pool (16 keys):</strong>
                            <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px;">
                                ${this.generateKeyPoolVisualization(keyIndex)}
                            </div>
                            <div style="font-size: 10px; color: #666; margin-top: 4px;">
                                * Random key selection from pool. Server sees only encrypted blob (blind).
                            </div>
                        </div>
                    `;
                }
            } catch(e) {
                keyIndexDisplay = 'Parse error';
            }
        }

        const copyText = `Session Key: ${sessionKeyHex}
Message ID: ${msg.id}
From: ${msg.from}
Key Index: ${keyIndexDisplay}
Has Phrase: ${msg.has_phrase ? 'Yes' : 'No'}
Encrypted: ${msg.encrypted}
Decrypted: ${displayText}
Timestamp: ${DuoNetUI.formatTime(msg.timestamp)}`;

        detailsDiv.innerHTML = `
            <div style="font-family: monospace; font-size: 11px; word-break: break-all; padding: 8px;">
                <div style="margin-bottom: 8px; padding: 4px; background: #e3f2fd; border-radius: 4px;">
                    <details>
                        <summary style="cursor: pointer; font-weight: bold;">🔑 Session Key (click to show)</summary>
                        <code style="font-size: 10px; margin-top: 8px; display: block; word-break: break-all;">${DuoNetUI.escapeHtml(sessionKeyHex)}</code>
                    </details>
                </div>

                <div style="margin-bottom: 8px; padding: 4px; background: #f5f5f5; border-radius: 4px;">
                    <strong>📝 Message ID:</strong><br>
                    <code style="font-size: 10px;">${DuoNetUI.escapeHtml(msg.id)}</code>
                </div>

                <div style="margin-bottom: 8px; padding: 4px; background: #f5f5f5; border-radius: 4px;">
                    <strong>👤 From:</strong><br>
                    <code style="font-size: 10px;">${DuoNetUI.escapeHtml(msg.from)}</code>
                </div>

                <div style="margin-bottom: 8px; padding: 4px; background: #fff3e0; border-radius: 4px;">
                    <strong>🎲 LRP Key Index:</strong><br>
                    <code style="font-size: 10px; font-weight: bold; color: #e65100;">${DuoNetUI.escapeHtml(keyIndexDisplay)}</code>
                    ${poolDisplay}
                </div>

                <div style="margin-bottom: 8px; padding: 4px; background: #f5f5f5; border-radius: 4px;">
                    <strong>🔐 Has phrase:</strong><br>
                    <code style="font-size: 10px;">${msg.has_phrase ? 'Yes' : 'No'}</code>
                </div>

                <div style="margin-bottom: 8px; padding: 4px; background: #f5f5f5; border-radius: 4px;">
                    <strong>📦 Encrypted (with key_index prefix):</strong><br>
                    <details>
                        <summary style="cursor: pointer; color: #666;">Show full</summary>
                        <code style="font-size: 10px;">${DuoNetUI.escapeHtml(msg.encrypted)}</code>
                    </details>
                    <div style="font-size: 9px; color: #666; margin-top: 4px;">
                        Format: [1 byte key_index][12 bytes nonce][ciphertext + tag + padding]
                    </div>
                </div>

                <div style="margin-bottom: 8px; padding: 4px; background: #e8f5e9; border-radius: 4px;">
                    <strong>📄 Decrypted:</strong><br>
                    <code style="font-size: 10px;">${DuoNetUI.escapeHtml(displayText || '')}</code>
                </div>

                <div style="margin-bottom: 8px; padding: 4px; background: #f5f5f5; border-radius: 4px;">
                    <strong>⏰ Timestamp:</strong><br>
                    <code style="font-size: 10px;">${DuoNetUI.formatTime(msg.timestamp)}</code>
                </div>

                <hr>
                <button id="copyDetailsBtn" style="margin-top: 8px; padding: 6px 12px; font-size: 11px; width: 100%; background: #2196f3; color: white; border: none; border-radius: 4px; cursor: pointer;">
                    📋 Copy all details
                </button>
            </div>
        `;

        const copyBtn = document.getElementById('copyDetailsBtn');
        if (copyBtn) {
            copyBtn.onclick = async () => {
                try {
                    await navigator.clipboard.writeText(copyText);
                    const originalText = copyBtn.textContent;
                    copyBtn.textContent = '✅ Copied!';
                    setTimeout(() => { copyBtn.textContent = originalText; }, 1500);
                    DuoNetUI.showToast('✅ Copied to clipboard', 'success');
                } catch (err) {
                    DuoNetUI.showToast('❌ Failed to copy', 'error');
                }
            };
        }

        this.showPackets(msg.encrypted, msg.is_own, keyIndex);
    }

    showSystemDetails(msg) {
        const detailsDiv = document.getElementById('messageDetails');
        const packetsDiv = document.getElementById('packets');
        if (!detailsDiv) return;

        let systemData = {};
        if (msg.system_data) {
            try {
                systemData = typeof msg.system_data === 'string'
                    ? JSON.parse(msg.system_data)
                    : msg.system_data;
            } catch(e) {}
        }

        detailsDiv.innerHTML = `
            <div style="font-family: monospace; font-size: 11px; padding: 8px;">
                <div style="margin-bottom: 8px; background: #e3f2fd; padding: 8px; border-radius: 4px;">
                    <strong>📢 СИСТЕМНОЕ СООБЩЕНИЕ</strong>
                </div>
                <div style="margin-bottom: 8px;">
                    <strong>📝 Тип:</strong> ${msg.system_type || 'UNKNOWN'}
                </div>
                <div style="margin-bottom: 8px;">
                    <strong>🆔 Rotation ID:</strong><br>
                    <code style="font-size: 10px;">${systemData.rotation_id || 'N/A'}</code>
                </div>
                <div style="margin-bottom: 8px;">
                    <strong>🔑 Эфемерный публичный ключ:</strong><br>
                    <code style="font-size: 9px; word-break: break-all;">${systemData.eph_public_key || 'N/A'}</code>
                </div>
                <div style="margin-bottom: 8px;">
                    <strong>⏰ Истекает:</strong> ${systemData.expires_at ? new Date(systemData.expires_at * 1000).toLocaleString() : 'N/A'}
                </div>
                <div style="margin-bottom: 8px;">
                    <strong>👤 Отправитель:</strong> ${msg.from_id || 'N/A'}
                </div>
                <div style="margin-bottom: 8px;">
                    <strong>📦 Полные данные:</strong><br>
                    <details>
                        <summary style="cursor: pointer;">Показать JSON</summary>
                        <pre style="background: #f5f5f5; padding: 8px; overflow-x: auto; font-size: 9px;">${JSON.stringify(systemData, null, 2)}</pre>
                    </details>
                </div>
            </div>
        `;

        packetsDiv.innerHTML = `
            <div class="packet" style="background: #e3f2fd; border-left: 3px solid #2196f3;">
                <div><strong>[SYSTEM] ${msg.system_type}</strong></div>
                <div style="font-size: 10px; margin-top: 4px;">Rotation ID: ${systemData.rotation_id || 'N/A'}</div>
                <div style="font-size: 9px; color: #666; margin-top: 4px;">Это системное сообщение протокола ротации ключей. Сервер не видит его содержимое.</div>
            </div>
        `;
    }

    generateKeyPoolVisualization(selectedIndex) {
        let html = '';
        for (let i = 0; i < 16; i++) {
            const isSelected = (i === selectedIndex);
            const bgColor = isSelected ? '#4caf50' : '#e0e0e0';
            const textColor = isSelected ? 'white' : '#333';
            const extraStyle = isSelected ? 'box-shadow: 0 0 0 2px #2196f3;' : '';
            html += `
                <div style="
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    width: 32px;
                    height: 32px;
                    background: ${bgColor};
                    color: ${textColor};
                    border-radius: 4px;
                    font-size: 10px;
                    font-weight: bold;
                    ${extraStyle}
                ">
                    K${i}
                </div>
            `;
        }
        return html;
    }

    showPackets(encryptedHex, isOwn, keyIndex = null) {
        const packetsDiv = document.getElementById('packets');
        if (!packetsDiv) return;

        if (!encryptedHex) {
            packetsDiv.innerHTML = '<div class="loading">No encryption data</div>';
            return;
        }

        const firstByte = encryptedHex.substring(0, 2);
        const restData = encryptedHex.substring(2);

        const packetSize = 64;
        let packetsHtml = '';

        const keyIndexValue = keyIndex !== null ? keyIndex : (parseInt(firstByte, 16) || '?');
        packetsHtml += `
            <div class="packet" style="background: #fff3e0; border-left: 3px solid #ff9800;">
                <div><strong>[HEADER] LRP Key Index</strong></div>
                <div style="font-size: 10px;">Value: K${keyIndexValue} (0x${firstByte})</div>
                <div style="font-size: 9px; color: #666;">First byte of encrypted data - which key from pool was used</div>
            </div>
        `;

        if (restData.length >= 24) {
            const nonce = restData.substring(0, 24);
            packetsHtml += `
                <div class="packet" style="background: #e3f2fd; border-left: 3px solid #2196f3;">
                    <div><strong>[HEADER] Nonce (IV)</strong> - 12 bytes</div>
                    <code style="font-size: 9px; word-break: break-all;">${DuoNetUI.escapeHtml(nonce)}</code>
                    <div style="font-size: 9px; color: #666;">Unique for each message - prevents replay attacks</div>
                </div>
            `;
        }

        const remainingData = restData.substring(24);
        if (remainingData.length > 0) {
            const remainingPackets = Math.ceil(remainingData.length / packetSize);
            for (let i = 0; i < remainingPackets; i++) {
                const start = i * packetSize;
                const end = Math.min(start + packetSize, remainingData.length);
                const packetData = remainingData.substring(start, end);
                const direction = isOwn ? 'outgoing' : 'incoming';
                const packetLabel = i === 0 ? 'Ciphertext + GCM Tag + Padding' : 'Continuation';

                packetsHtml += `
                    <div class="packet">
                        <div><strong>[${direction.toUpperCase()}] ${packetLabel} - Packet ${i+1}/${remainingPackets}</strong> (${packetData.length} bytes)</div>
                        <code style="font-size: 9px; word-break: break-all;">${DuoNetUI.escapeHtml(packetData)}</code>
                    </div>
                `;
            }
        }

        packetsDiv.innerHTML = packetsHtml;
    }
}

window.DuoNetMessages = DuoNetMessages;
