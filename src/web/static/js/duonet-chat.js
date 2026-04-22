/**
 * DuoNet Chat Module - Facade
 */

class DuoNetChat {
    constructor(contactId, token, currentUserId) {
        this.contactId = contactId;
        this.token = token;
        this.currentUserId = currentUserId;
        this.core = null;
    }

    async init() {
        this.core = new DuoNetCore(this.contactId, this.token, this.currentUserId);
        const success = await this.core.init();
        if (!success) {
            DuoNetUI.showErrorInElement(
                document.getElementById('messages'),
                'Failed to initialize chat. Please refresh.'
            );
        }
        this.setupButtons();
    }

    setupButtons() {
        const setBtn = document.getElementById('setPhraseBtn');
        const clearBtn = document.getElementById('clearPhraseBtn');
        const rotateBtn = document.getElementById('rotateKeyBtn');
        const filterAll = document.getElementById('filterAll');
        const filterSent = document.getElementById('filterSent');
        const filterReceived = document.getElementById('filterReceived');

        if (setBtn) setBtn.onclick = () => this.showPhraseModal();
        if (clearBtn) clearBtn.onclick = () => this.clearPhrase();

        // ========== НОВЫЙ ОБРАБОТЧИК ДЛЯ КНОПКИ РОТАЦИИ ==========
        if (rotateBtn) {
            rotateBtn.onclick = () => this.rotateKey();
        }

        if (filterAll) filterAll.onclick = () => this.setFilter('all');
        if (filterSent) filterSent.onclick = () => this.setFilter('sent');
        if (filterReceived) filterReceived.onclick = () => this.setFilter('received');
    }

    // ========== НОВЫЙ МЕТОД ДЛЯ РОТАЦИИ ==========
    async rotateKey() {
        if (!this.core || !this.core.rotation) {
            DuoNetUI.showToast('Chat not initialized', 'error');
            return;
        }
        console.log('🔄 Rotate key button clicked, calling rotation.initiate()');
        await this.core.rotation.initiate();
    }

    async setPhrase(phrase) {
        try {
            const response = await fetch(`/api/web/chat/${this.contactId}/phrase`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phrase: phrase })
            });
            const result = await response.json();
            if (result.success) {
                this.core.phraseKnown = true;
                this.core.currentPhrase = phrase;
                DuoNetCrypto.storePhrase(this.contactId, phrase);
                DuoNetUI.updatePhraseUI(true, true);
                await this.core.messages.loadMessages();
                return true;
            }
        } catch (error) {
            DuoNetUI.showToast('Failed to set phrase', 'error');
        }
        return false;
    }

    async clearPhrase() {
        try {
            const response = await fetch(`/api/web/chat/${this.contactId}/phrase`, { method: 'DELETE' });
            const result = await response.json();
            if (result.success) {
                this.core.phraseKnown = false;
                this.core.currentPhrase = null;
                DuoNetCrypto.clearStoredPhrase(this.contactId);
                DuoNetUI.updatePhraseUI(false, false);
                await this.core.messages.loadMessages();
                return true;
            }
        } catch (error) {
            DuoNetUI.showToast('Failed to clear phrase', 'error');
        }
        return false;
    }

    showPhraseModal() {
        const modal = document.getElementById('phraseModal');
        const input = document.getElementById('phraseInput');
        if (input) input.value = '';

        const onSave = async () => {
            const phrase = input.value.trim();
            if (phrase) await this.setPhrase(phrase);
            DuoNetUI.hideModal('phraseModal');
        };

        const onCancel = () => DuoNetUI.hideModal('phraseModal');

        const submitBtn = document.getElementById('phraseSubmit');
        const cancelBtn = document.getElementById('phraseCancel');

        if (submitBtn) {
            submitBtn.onclick = onSave;
            cancelBtn.onclick = onCancel;
        }

        DuoNetUI.showModal('phraseModal');
        if (input) input.focus();
    }

    setFilter(filter) {
        const packets = document.querySelectorAll('#packets .packet');
        packets.forEach(p => {
            const text = p.querySelector('div:first-child')?.textContent || '';
            const direction = text.match(/\[(.*?)\]/)?.[1];
            if (filter === 'all') p.style.display = 'block';
            else if (filter === 'sent' && direction === 'outgoing') p.style.display = 'block';
            else if (filter === 'received' && direction === 'incoming') p.style.display = 'block';
            else p.style.display = 'none';
        });
    }

    destroy() {
        if (this.core) this.core.destroy();
    }
}

window.DuoNetChat = DuoNetChat;
