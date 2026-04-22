/**
 * DuoNet UI Module
 * UI components: toasts, modals, formatting, notifications
 */

class DuoNetUI {
    // =========================================================================
    // Toast notifications
    // =========================================================================

    /**
     * Show a toast notification
     * @param {string} message - Message to display
     * @param {string} type - Type: 'info', 'success', 'error'
     */
    static showToast(message, type = 'info') {
        const existingToast = document.querySelector('.toast');
        if (existingToast) existingToast.remove();

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        document.body.appendChild(toast);

        setTimeout(() => toast.remove(), 3000);
    }

    // =========================================================================
    // Modal management
    // =========================================================================

    /**
     * Show modal
     * @param {string} modalId - Modal element ID
     */
    static showModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) modal.style.display = 'block';
    }

    /**
     * Hide modal
     * @param {string} modalId - Modal element ID
     */
    static hideModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) modal.style.display = 'none';
    }

    /**
     * Show error modal
     * @param {string} message - Error message
     * @param {string} title - Modal title (default: 'Error')
     */
    static showError(message, title = 'Error') {
        const modal = document.getElementById('errorModal');
        const titleEl = document.getElementById('errorTitle');
        const messageEl = document.getElementById('errorMessage');

        if (titleEl) titleEl.textContent = title;
        if (messageEl) messageEl.textContent = message;
        if (modal) this.showModal('errorModal');
    }

    /**
     * Hide error modal
     */
    static hideError() {
        this.hideModal('errorModal');
    }

    /**
     * Setup all modals with their close handlers
     * This should be called after DOM is loaded
     */
    static setupAllModals() {
        // Phrase modal
        const phraseModal = document.getElementById('phraseModal');
        const phraseCancel = document.getElementById('phraseCancel');
        if (phraseCancel) {
            phraseCancel.onclick = () => this.hideModal('phraseModal');
        }
        if (phraseModal) {
            phraseModal.addEventListener('click', (e) => {
                if (e.target === phraseModal) this.hideModal('phraseModal');
            });
        }

        // Error modal
        const errorModal = document.getElementById('errorModal');
        const errorClose = document.getElementById('errorClose');
        if (errorClose) {
            errorClose.onclick = () => this.hideError();
        }
        if (errorModal) {
            errorModal.addEventListener('click', (e) => {
                if (e.target === errorModal) this.hideError();
            });
        }

        // Confirm modal (rotation)
        const confirmModal = document.getElementById('confirmModal');
        const confirmNo = document.getElementById('confirmNo');
        if (confirmNo) {
            confirmNo.onclick = () => this.hideModal('confirmModal');
        }
        if (confirmModal) {
            confirmModal.addEventListener('click', (e) => {
                if (e.target === confirmModal) this.hideModal('confirmModal');
            });
        }

        // System message modal
        const sysModal = document.getElementById('systemMessageModal');
        const sysClose = document.getElementById('sysMsgClose');
        if (sysClose) {
            sysClose.onclick = () => this.hideModal('systemMessageModal');
        }
        if (sysModal) {
            sysModal.addEventListener('click', (e) => {
                if (e.target === sysModal) this.hideModal('systemMessageModal');
            });
        }

        // Escape key for all modals
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.hideModal('phraseModal');
                this.hideError();
                this.hideModal('confirmModal');
                this.hideModal('systemMessageModal');
            }
        });
    }

    // =========================================================================
    // Formatting helpers
    // =========================================================================

    /**
     * Format timestamp to readable time
     * @param {number} timestamp - Unix timestamp in seconds
     * @returns {string} Formatted time string
     */
    static formatTime(timestamp) {
        return new Date(timestamp * 1000).toLocaleString();
    }

    /**
     * Format time only (HH:MM:SS)
     * @param {number} timestamp - Unix timestamp in seconds
     * @returns {string} Formatted time string
     */
    static formatTimeShort(timestamp) {
        return new Date(timestamp * 1000).toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    }

    /**
     * Escape HTML to prevent XSS
     * @param {string} text - Text to escape
     * @returns {string} Escaped text
     */
    static escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // =========================================================================
    // UI update helpers
    // =========================================================================

    /**
     * Update online status display
     * @param {boolean} isOnline - Whether the contact is online
     */
    static updateOnlineStatus(isOnline) {
        const onlineStatusSpan = document.getElementById('onlineStatus');
        if (onlineStatusSpan) {
            onlineStatusSpan.textContent = isOnline ? '🟢 Online' : '⚪ Offline';
            onlineStatusSpan.className = isOnline ? 'status-online' : 'status-offline';
        }
    }

    /**
     * Update phrase UI based on state
     * @param {boolean} hasPhrase - Whether phrase is set on server
     * @param {boolean} phraseEntered - Whether phrase is entered in current session
     */
    static updatePhraseUI(hasPhrase, phraseEntered) {
        const statusSpan = document.getElementById('phraseStatus');
        const statusText = document.getElementById('phraseStatusText');
        const clearBtn = document.getElementById('clearPhraseBtn');

        if (!statusSpan || !statusText) return;

        if (phraseEntered) {
            statusSpan.className = 'phrase-status has-phrase';
            statusText.textContent = '🔐 Phrase active';
            if (clearBtn) clearBtn.style.display = 'inline-block';
        } else if (hasPhrase) {
            statusSpan.className = 'phrase-status has-phrase';
            statusText.textContent = '🔐 Phrase set (not entered)';
            if (clearBtn) clearBtn.style.display = 'inline-block';
        } else {
            statusSpan.className = 'phrase-status no-phrase';
            statusText.textContent = '🔓 No phrase';
            if (clearBtn) clearBtn.style.display = 'none';
        }
    }

    /**
     * Update rotation UI based on status
     * @param {Object} status - Rotation status object
     */
    static updateRotationUI(status) {
        const infoDiv = document.getElementById('rotationInfo');
        const btn = document.getElementById('rotateKeyBtn');

        if (!infoDiv || !btn) return;

        if (status.mode === 'transition') {
            btn.disabled = true;
            btn.textContent = '⏳ Waiting for confirmation...';
            const hoursLeft = Math.ceil(status.deadline_remaining / 3600);
            infoDiv.innerHTML = `<span>⏳ Waiting for confirmation (${hoursLeft}h)</span>`;
        } else if (status.mode === 'rotated') {
            const myCooldown = status.my_cooldown_remaining || 0;
            const peerCooldown = status.peer_cooldown_remaining || 0;

            if (myCooldown > 0) {
                btn.disabled = true;
                const hours = Math.floor(myCooldown / 3600);
                const minutes = Math.floor((myCooldown % 3600) / 60);
                btn.textContent = `🔒 Update key (${hours}h ${minutes}m)`;
                infoDiv.innerHTML = `<span>🔒 Key updated. Next rotation in ${hours}h ${minutes}m</span>`;
            } else {
                btn.disabled = false;
                btn.textContent = '🔄 Update key';
                infoDiv.innerHTML = `<span>✅ Key updated. You can rotate again</span>`;
            }

            if (peerCooldown > 0) {
                const hours = Math.floor(peerCooldown / 3600);
                const minutes = Math.floor((peerCooldown % 3600) / 60);
                infoDiv.innerHTML += ` | <span>👥 Peer can update in ${hours}h ${minutes}m</span>`;
            }
        } else {
            const myCooldown = status.my_cooldown_remaining || 0;
            const peerCooldown = status.peer_cooldown_remaining || 0;

            if (myCooldown === 0) {
                btn.disabled = false;
                btn.textContent = '🔄 Update key';
                infoDiv.innerHTML = `<span>👤 You: ✅ Can update</span>`;
            } else {
                const hours = Math.floor(myCooldown / 3600);
                const minutes = Math.floor((myCooldown % 3600) / 60);
                btn.disabled = true;
                btn.textContent = `🔒 Update key (${hours}h ${minutes}m)`;
                infoDiv.innerHTML = `<span>👤 You: ⏳ Can update in ${hours}h ${minutes}m</span>`;
            }

            if (peerCooldown === 0) {
                infoDiv.innerHTML += ` | <span>👥 Peer: ✅ Can update</span>`;
            } else {
                const hours = Math.floor(peerCooldown / 3600);
                const minutes = Math.floor((peerCooldown % 3600) / 60);
                infoDiv.innerHTML += ` | <span>👥 Peer: ⏳ Can update in ${hours}h ${minutes}m</span>`;
            }
        }
    }

    // =========================================================================
    // Message element creation
    // =========================================================================

    /**
     * Create message element
     * @param {Object} msg - Message object
     * @param {boolean} isOwn - Whether message is from current user
     * @param {string|null} decryptedText - Decrypted message text
     * @param {boolean} needsPhrase - Whether phrase is needed for decryption
     * @returns {HTMLElement} Message DOM element
     */
    static createMessageElement(msg, isOwn, decryptedText, needsPhrase) {
        const messageDiv = document.createElement('div');
        messageDiv.setAttribute('data-message-id', msg.id);
        messageDiv.setAttribute('data-timestamp', msg.timestamp);
        messageDiv.className = `message ${isOwn ? 'message-own' : 'message-other'}`;

        let displayText = decryptedText;
        let needsPhraseInput = false;

        if (!displayText) {
            if (msg.has_phrase) {
                if (!this.currentPhrase && !msg.is_own) {
                    displayText = '🔒 [Требуется дополнительная фраза]';
                    needsPhraseInput = true;
                } else {
                    displayText = '🔒 [Зашифрованное сообщение]';
                }
            } else {
                displayText = '🔒 [Зашифрованное сообщение]';
            }
            messageDiv.classList.add('message-hidden');
        }

        let decryptButtonHtml = '';
        if (needsPhraseInput && !isOwn) {
            decryptButtonHtml = `
                <div class="decrypt-prompt">
                    <span>🔐 Требуется фраза</span>
                    <button onclick="window.dispatchEvent(new CustomEvent('showPhraseModal'))">Ввести фразу</button>
                </div>
            `;
        }

        messageDiv.innerHTML = `
            <div><strong>${this.escapeHtml(isOwn ? 'Я' : (msg.from || msg.from_id))}:</strong> ${this.escapeHtml(displayText)}</div>
            <div class="message-time">${this.formatTime(msg.timestamp)}</div>
            ${decryptButtonHtml}
        `;

        return messageDiv;
    }

    /**
     * Create system message element
     * @param {Object} msg - System message object
     * @returns {HTMLElement} System message DOM element
     */
    static createSystemMessageElement(msg) {
        let icon = '📢';
        let text = 'System message';
        let className = 'system-message';

        switch (msg.system_type) {
            case 'rotation_request':
                icon = '🔄';
                const senderName = (msg.from_id || '').split('@')[1]?.split('.')[0] || msg.from_id;
                text = `${senderName} requested key rotation`;
                className += ' rotation_request';
                break;
            case 'rotation_ack':
                icon = '✅';
                const ackName = (msg.from_id || '').split('@')[1]?.split('.')[0] || msg.from_id;
                text = `${ackName} confirmed key rotation`;
                className += ' rotation_ack';
                break;
            case 'rotation_confirm':
                icon = '🔐';
                const confirmName = (msg.from_id || '').split('@')[1]?.split('.')[0] || msg.from_id;
                text = `${confirmName} confirmed key rotation`;
                className += ' rotation_confirm';
                break;
            case 'rotation_complete':
                icon = '✅';
                text = 'Key rotation completed';
                className += ' rotation_complete';
                break;
            case 'rotation_reject':
                icon = '❌';
                const rejectName = (msg.from_id || '').split('@')[1]?.split('.')[0] || msg.from_id;
                text = `${rejectName} rejected key rotation`;
                className += ' rotation_reject';
                break;
            case 'rotation_timeout':
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
        systemDiv.setAttribute('data-message-id', msg.id);
        systemDiv.setAttribute('data-timestamp', msg.timestamp);

        const timeStr = this.formatTimeShort(msg.timestamp);

        systemDiv.innerHTML = `
            <div style="display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: center;">
                <span>${icon}</span>
                <span>${this.escapeHtml(text)}</span>
                <span style="font-size: 0.65rem; opacity: 0.7;">[${timeStr}]</span>
            </div>
        `;

        return systemDiv;
    }

    // =========================================================================
    // Scroll helpers
    // =========================================================================

    /**
     * Scroll messages container to bottom
     * @param {HTMLElement} container - Messages container element
     * @param {boolean} smooth - Whether to animate scroll
     */
    static scrollToBottom(container, smooth = true) {
        if (!container) return;
        container.scrollTo({
            top: container.scrollHeight,
            behavior: smooth ? 'smooth' : 'auto'
        });
    }

    // =========================================================================
    // Loading and error states
    // =========================================================================

    /**
     * Show loading indicator in element
     * @param {HTMLElement} element - Target element
     * @param {string} message - Loading message
     */
    static showLoading(element, message = 'Loading...') {
        if (element) {
            element.innerHTML = `<div class="loading">${this.escapeHtml(message)}</div>`;
        }
    }

    /**
     * Show error in element
     * @param {HTMLElement} element - Target element
     * @param {string} message - Error message
     */
    static showErrorInElement(element, message) {
        if (element) {
            element.innerHTML = `<div class="error">❌ ${this.escapeHtml(message)}</div>`;
        }
    }

    /**
     * Clear element content
     * @param {HTMLElement} element - Target element
     */
    static clearElement(element) {
        if (element) element.innerHTML = '';
    }
}

// Export for use in other modules
window.DuoNetUI = DuoNetUI;
