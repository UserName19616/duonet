/**
 * DuoNet System Messages Module
 * Handles rotation protocol messages (client-only, server blind)
 * Processes REQUEST, ACCEPT, CONFIRM, COMPLETE, REJECT, TIMEOUT
 *
 * System messages are displayed in the chat area and show details in the right panel
 * No modal dialogs - all information is shown in the crypto panel
 */

class DuoNetSystemHandler {
    constructor(core) {
        this.core = core;
        this.processed = new Set();
    }

    async handle(decryptedText, originalMsg) {
        console.log('[SystemHandler] Received message:', decryptedText.substring(0, 200));

        let data;
        try {
            data = JSON.parse(decryptedText);
            if (data.__type !== 'system') return false;
        } catch (e) {
            return false;
        }

        const rotationId = data.rotation_id;
        const subtype = data.subtype?.toUpperCase();

        if (!rotationId || !subtype) {
            console.warn('Invalid system message:', data);
            return false;
        }

        const key = `${rotationId}_${subtype}`;
        if (this.processed.has(key)) {
            console.log(`Duplicate system message ${key}, ignoring`);
            return true;
        }
        this.processed.add(key);

        if (this.processed.size > 100) {
            const vals = this.processed.values();
            for (let i = 0; i < 50; i++) {
                this.processed.delete(vals.next().value);
            }
        }

        // Display system message in chat UI
        this.addToUI({
            id: originalMsg.message_id,
            from_id: originalMsg.from,
            timestamp: originalMsg.timestamp || Math.floor(Date.now() / 1000),
            system_type: subtype,
            system_data: data,
            rotation_id: rotationId,
            expires_at: data.expires_at,
            eph_public_key: data.eph_public_key
        });

        // Handle by subtype with role checking
        switch (subtype) {
            case 'ROTATION_REQUEST':
                // REQUEST can be processed by anyone (shows buttons for responder)
                if (originalMsg.from !== this.core.currentUserId && this.core.rotation) {
                    console.log('Rotation REQUEST received, showing buttons');
                    await this.core.rotation.processIncomingRequest(
                        rotationId,
                        data.eph_public_key,
                        data.expires_at
                    );
                }
                break;

            case 'ROTATION_ACCEPT':
                // ACCEPT should only be processed by the INITIATOR (who has the saved ephPrivateKey)
                if (originalMsg.from !== this.core.currentUserId && this.core.rotation) {
                    const savedKey = this.core.rotation.loadEphPrivateKey(rotationId);
                    if (savedKey) {
                        console.log('Rotation ACCEPT received by initiator, processing...');
                        await this.core.rotation.processAccept(rotationId, data.eph_public_key);
                    } else {
                        console.log('Rotation ACCEPT received but I am not initiator (no saved key), ignoring');
                    }
                }
                break;

            case 'ROTATION_CONFIRM':
                // CONFIRM should only be processed by the RESPONDER (who sent ACCEPT and has saved key)
                if (originalMsg.from !== this.core.currentUserId && this.core.rotation) {
                    const savedKey = this.core.rotation.loadEphPrivateKey(rotationId);
                    // Responder has savedKey and is NOT the sender of this message
                    if (savedKey) {
                        console.log('Rotation CONFIRM received by responder, processing...');
                        await this.core.rotation.processConfirm(rotationId);
                    } else {
                        console.log('Rotation CONFIRM received but I am not responder (no saved key), ignoring');
                    }
                }
                break;

            case 'ROTATION_COMPLETE':
                // COMPLETE can be processed by anyone (just updates UI and cleans up)
                if (this.core.rotation) {
                    console.log('Rotation COMPLETE received, updating UI');
                    await this.core.rotation.processComplete(rotationId);
                    await this.core.messages.loadMessages(true);  // ← ДОБАВИТЬ ЭТУ СТРОКУ
                }
                break;

            case 'ROTATION_REJECT':
                if (this.core.rotation) {
                    console.log('Rotation REJECT received');
                    await this.core.rotation.processReject(rotationId);
                    await this.core.messages.loadMessages(true);
                }
                break;

            case 'ROTATION_TIMEOUT':
                if (this.core.rotation) {
                    console.log('Rotation TIMEOUT received');
                    await this.core.rotation.processTimeout(rotationId);
                    await this.core.messages.loadMessages(true);
                }
                break;

            default:
                console.log('Unknown system message type:', subtype);
        }
        return true;
    }

    addToUI(msg) {
        const messagesDiv = document.getElementById('messages');
        if (!messagesDiv) return;
        if (document.querySelector(`[data-message-id="${msg.id}"]`)) return;

        const now = Math.floor(Date.now() / 1000);
        let isExpired = false;
        let rotationId = msg.rotation_id;
        let expiresAt = msg.expires_at;

        if (msg.system_type === 'ROTATION_REQUEST' && expiresAt) {
            isExpired = now > expiresAt;
        }

        let isResolved = false;
        if (rotationId && this.core.messages) {
            isResolved = this.core.messages.isRotationResolved(rotationId);
        }

        const element = this._createSystemMessageElement(msg);
        element.setAttribute('data-message-id', msg.id);
        element.setAttribute('data-rotation-id', rotationId || '');
        element.setAttribute('data-system-type', msg.system_type);
        element.setAttribute('data-timestamp', msg.timestamp);
        element.setAttribute('data-system-data', JSON.stringify(msg.system_data || {}));

        // Add buttons for active REQUEST (incoming, not expired, not resolved)
        if (msg.system_type === 'ROTATION_REQUEST' &&
            msg.from_id !== this.core.currentUserId &&
            !isResolved &&
            !isExpired &&
            this.core.rotation) {

            const buttonContainer = document.createElement('div');
            buttonContainer.className = 'rotation-buttons';
            buttonContainer.style.display = 'flex';
            buttonContainer.style.gap = '8px';
            buttonContainer.style.justifyContent = 'center';
            buttonContainer.style.marginTop = '8px';

            const acceptBtn = document.createElement('button');
            acceptBtn.textContent = '✅ Accept';
            acceptBtn.className = 'success';
            acceptBtn.style.padding = '4px 12px';
            acceptBtn.style.fontSize = '11px';
            acceptBtn.onclick = async (e) => {
                e.stopPropagation();
                acceptBtn.disabled = true;
                acceptBtn.textContent = '⏳ Accepting...';
                const rejectBtn = buttonContainer.querySelector('.danger');
                if (rejectBtn) rejectBtn.disabled = true;

                await this.core.rotation.accept(rotationId);
                this.removeButtonsByRotationId(rotationId);
                setTimeout(() => this.core.messages.loadMessages(true), 500);
            };

            const rejectBtn = document.createElement('button');
            rejectBtn.textContent = '❌ Reject';
            rejectBtn.className = 'danger';
            rejectBtn.style.padding = '4px 12px';
            rejectBtn.style.fontSize = '11px';
            rejectBtn.onclick = async (e) => {
                e.stopPropagation();
                rejectBtn.disabled = true;
                rejectBtn.textContent = '⏳ Rejecting...';
                const acceptBtnLocal = buttonContainer.querySelector('.success');
                if (acceptBtnLocal) acceptBtnLocal.disabled = true;

                await this.core.rotation.reject(rotationId);
                this.removeButtonsByRotationId(rotationId);
                setTimeout(() => this.core.messages.loadMessages(true), 500);
            };

            buttonContainer.appendChild(acceptBtn);
            buttonContainer.appendChild(rejectBtn);
            element.appendChild(buttonContainer);
        } else if (msg.system_type === 'ROTATION_REQUEST' && (isResolved || isExpired)) {
            const statusSpan = document.createElement('span');
            statusSpan.textContent = isResolved ? ' ✓ Processed' : ' ⏰ Expired';
            statusSpan.style.color = isResolved ? '#4caf50' : '#f44336';
            statusSpan.style.marginLeft = '8px';
            statusSpan.style.fontSize = '11px';
            const firstDiv = element.querySelector('div:first-child');
            if (firstDiv) {
                firstDiv.appendChild(statusSpan);
            }
        }

        if (isExpired) {
            element.classList.add('system-expired');
            element.style.opacity = '0.6';
        }

        element.onclick = () => this.showDetailsInPanel(msg);

        messagesDiv.appendChild(element);
        this._scrollToBottom(messagesDiv);
    }

    _createSystemMessageElement(msg) {
        let icon = '📢';
        let text = 'System message';
        let className = 'system-message';

        switch (msg.system_type) {
            case 'ROTATION_REQUEST':
                icon = '🔄';
                const senderName = (msg.from_id || '').split('@')[1]?.split('.')[0] || msg.from_id;
                text = `${senderName} requested key rotation`;
                className += ' rotation_request';
                break;
            case 'ROTATION_ACCEPT':
                icon = '✅';
                const ackName = (msg.from_id || '').split('@')[1]?.split('.')[0] || msg.from_id;
                text = `${ackName} accepted key rotation`;
                className += ' rotation_ack';
                break;
            case 'ROTATION_CONFIRM':
                icon = '🔐';
                const confirmName = (msg.from_id || '').split('@')[1]?.split('.')[0] || msg.from_id;
                text = `${confirmName} confirmed key rotation`;
                className += ' rotation_confirm';
                break;
            case 'ROTATION_COMPLETE':
                icon = '✅';
                text = 'Key rotation completed';
                className += ' rotation_complete';
                break;
            case 'ROTATION_REJECT':
                icon = '❌';
                const rejectName = (msg.from_id || '').split('@')[1]?.split('.')[0] || msg.from_id;
                text = `${rejectName} rejected key rotation`;
                className += ' rotation_reject';
                break;
            case 'ROTATION_TIMEOUT':
                icon = '⏰';
                text = 'Key rotation request expired';
                className += ' rotation_timeout';
                break;
            default:
                text = msg.system_type || 'System message';
                className += ' system-default';
        }

        const systemDiv = document.createElement('div');
        systemDiv.className = className;

        const timeStr = this._formatTimeShort(msg.timestamp);

        systemDiv.innerHTML = `
            <div style="display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: center;">
                <span>${icon}</span>
                <span>${this._escapeHtml(text)}</span>
                <span style="font-size: 0.65rem; opacity: 0.7;">[${timeStr}]</span>
            </div>
        `;

        return systemDiv;
    }

    showDetailsInPanel(msg) {
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

        let statusText = msg.system_type || 'UNKNOWN';
        let statusColor = '#666';
        if (msg.system_type === 'ROTATION_REQUEST') statusColor = '#ff9800';
        else if (msg.system_type === 'ROTATION_ACCEPT') statusColor = '#4caf50';
        else if (msg.system_type === 'ROTATION_CONFIRM') statusColor = '#2196f3';
        else if (msg.system_type === 'ROTATION_COMPLETE') statusColor = '#2e7d32';
        else if (msg.system_type === 'ROTATION_REJECT') statusColor = '#f44336';
        else if (msg.system_type === 'ROTATION_TIMEOUT') statusColor = '#9e9e9e';

        detailsDiv.innerHTML = `
            <div style="font-family: monospace; font-size: 11px; padding: 8px;">
                <div style="margin-bottom: 8px; background: ${statusColor}20; padding: 8px; border-radius: 4px; border-left: 3px solid ${statusColor};">
                    <strong>📢 СИСТЕМНОЕ СООБЩЕНИЕ</strong>
                    <span style="float: right; color: ${statusColor}; font-weight: bold;">${statusText}</span>
                </div>

                <div style="margin-bottom: 8px; padding: 4px; background: #f5f5f5; border-radius: 4px;">
                    <strong>🆔 Rotation ID:</strong><br>
                    <code style="font-size: 10px; word-break: break-all;">${this._escapeHtml(systemData.rotation_id || 'N/A')}</code>
                </div>

                <div style="margin-bottom: 8px; padding: 4px; background: #f5f5f5; border-radius: 4px;">
                    <strong>👤 Отправитель:</strong><br>
                    <code style="font-size: 10px;">${this._escapeHtml(msg.from_id || 'N/A')}</code>
                </div>

                <div style="margin-bottom: 8px; padding: 4px; background: #fff3e0; border-radius: 4px;">
                    <strong>🔑 Эфемерный публичный ключ:</strong><br>
                    <details>
                        <summary style="cursor: pointer;">Показать (${systemData.eph_public_key ? systemData.eph_public_key.length / 2 : 0} байт)</summary>
                        <code style="font-size: 9px; word-break: break-all; margin-top: 4px; display: block;">${this._escapeHtml(systemData.eph_public_key || 'N/A')}</code>
                    </details>
                </div>

                <div style="margin-bottom: 8px; padding: 4px; background: #f5f5f5; border-radius: 4px;">
                    <strong>⏰ Время получения:</strong><br>
                    <code style="font-size: 10px;">${this._formatTime(msg.timestamp)}</code>
                </div>

                ${systemData.expires_at ? `
                <div style="margin-bottom: 8px; padding: 4px; background: #f5f5f5; border-radius: 4px;">
                    <strong>⏰ Истекает:</strong><br>
                    <code style="font-size: 10px;">${this._formatTime(systemData.expires_at)}</code>
                </div>
                ` : ''}

                <div style="margin-bottom: 8px; padding: 4px; background: #e8f5e9; border-radius: 4px;">
                    <strong>📦 Полные данные (JSON):</strong><br>
                    <details>
                        <summary style="cursor: pointer;">Показать</summary>
                        <pre style="background: #1e1e1e; color: #d4d4d4; padding: 8px; overflow-x: auto; font-size: 9px; border-radius: 4px; margin-top: 4px;">${JSON.stringify(systemData, null, 2)}</pre>
                    </details>
                </div>

                <hr style="margin: 12px 0;">
                <div style="font-size: 9px; color: #666; text-align: center;">
                    🔒 Системное сообщение зашифровано так же, как обычное.<br>
                    Сервер не видит его содержимое.
                </div>
            </div>
        `;

        packetsDiv.innerHTML = `
            <div class="packet" style="background: ${statusColor}10; border-left: 3px solid ${statusColor};">
                <div><strong>[SYSTEM] ${msg.system_type}</strong></div>
                <div style="font-size: 10px; margin-top: 4px;">Rotation ID: ${this._escapeHtml(systemData.rotation_id || 'N/A')}</div>
                <div style="font-size: 9px; color: #666; margin-top: 8px;">
                    📌 Это системное сообщение протокола ротации ключей.<br>
                    🔐 Сервер является слепым ретранслятором и не видит содержимое.<br>
                    🔄 Протокол: REQUEST → ACCEPT → CONFIRM → COMPLETE
                </div>
            </div>
        `;
    }

    removeButtonsByRotationId(rotationId) {
        const allSystemMessages = document.querySelectorAll('.system-message');
        for (const msgElement of allSystemMessages) {
            const msgText = msgElement.textContent || '';
            if (msgText.includes(rotationId)) {
                const buttons = msgElement.querySelectorAll('.rotation-buttons');
                buttons.forEach(btn => btn.remove());

                if (!msgElement.querySelector('.processed-status')) {
                    const statusSpan = document.createElement('span');
                    statusSpan.textContent = ' ✓ Processed';
                    statusSpan.className = 'processed-status';
                    statusSpan.style.color = '#4caf50';
                    statusSpan.style.marginLeft = '8px';
                    statusSpan.style.fontSize = '11px';
                    const firstDiv = msgElement.querySelector('div:first-child');
                    if (firstDiv) {
                        firstDiv.appendChild(statusSpan);
                    }
                }
            }
        }
    }

    _formatTime(timestamp) {
        if (!timestamp) return '';
        return new Date(timestamp * 1000).toLocaleString();
    }

    _formatTimeShort(timestamp) {
        if (!timestamp) return '';
        return new Date(timestamp * 1000).toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    _escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    _scrollToBottom(container) {
        if (container) {
            container.scrollTop = container.scrollHeight;
        }
    }
}

window.DuoNetSystemHandler = DuoNetSystemHandler;
