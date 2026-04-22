/**
 * DuoNet Rotation Module V4
 * Client-only key rotation with ECDH (X25519) using tweetnacl
 * Server is blind - all messages are encrypted
 * Protocol: REQUEST → ACCEPT → CONFIRM → COMPLETE (or REJECT/TIMEOUT)
 *
 * State recovery from system messages (not localStorage)
 * Only ephPrivateKey is stored in localStorage (cannot be recovered from messages)
 */

class DuoNetRotation {
    constructor(core) {
        this.core = core;
        this.isPending = false;
        this.currentRotationId = null;
        this.currentStatus = null;
        this.currentExpiresAt = null;
        this._initialized = false;
        this._pendingRequest = null;
        this._pendingEphPrivateKey = null;
        this._pendingEphPublicKey = null;
        this._peerEphPublicKey = null;
        this._newSessionKey = null;
    }

    _getStorageKey() {
        return `duonet_rotation_key_${this.core.dialogId}`;
    }

    _saveEphPrivateKey(rotationId, ephPrivateKey, expiresAt) {
        const data = {
            rotationId: rotationId,
            ephPrivateKey: ephPrivateKey,
            expiresAt: expiresAt
        };
        localStorage.setItem(this._getStorageKey(), JSON.stringify(data));
        console.log(`[Rotation] Saved ephPrivateKey for ${rotationId}`);
    }

    _loadEphPrivateKey(rotationId) {
        const saved = localStorage.getItem(this._getStorageKey());
        if (!saved) return null;

        try {
            const data = JSON.parse(saved);
            if (data.rotationId === rotationId && !this.isExpired(data.expiresAt)) {
                return data.ephPrivateKey;
            }
        } catch (e) {
            console.error('[Rotation] Failed to parse saved key:', e);
        }
        return null;
    }

    loadEphPrivateKey(rotationId) {
        return this._loadEphPrivateKey(rotationId);
    }

    _clearEphPrivateKey() {
        localStorage.removeItem(this._getStorageKey());
        console.log('[Rotation] Cleared ephPrivateKey');
    }

    _cleanupExpiredKeys() {
        const prefix = 'duonet_rotation_key_';
        const now = Date.now() / 1000;
        let cleaned = 0;

        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            if (key && key.startsWith(prefix)) {
                try {
                    const data = JSON.parse(localStorage.getItem(key));
                    if (data.expiresAt && now > data.expiresAt) {
                        localStorage.removeItem(key);
                        cleaned++;
                    }
                } catch (e) {
                    localStorage.removeItem(key);
                    cleaned++;
                }
            }
        }

        if (cleaned > 0) {
            console.log(`[Rotation] Cleaned ${cleaned} expired keys`);
        }
    }

    isExpired(expiresAt) {
        return expiresAt && (Date.now() / 1000) > expiresAt;
    }

    async restoreStateFromMessages() {
        const messages = this.core.messages?.messages || [];

        const rotationMessages = messages.filter(m =>
            m.is_system &&
            ['REQUEST', 'ACCEPT', 'CONFIRM', 'COMPLETE', 'REJECT', 'TIMEOUT',
             'ROTATION_REQUEST', 'ROTATION_ACCEPT', 'ROTATION_CONFIRM',
             'ROTATION_COMPLETE', 'ROTATION_REJECT', 'ROTATION_TIMEOUT'].includes(m.system_type?.toUpperCase())
        );

        if (rotationMessages.length === 0) return false;

        const rotations = {};
        for (const msg of rotationMessages) {
            let rotationId = msg.rotation_id;
            if (!rotationId && msg.system_data) {
                try {
                    const data = typeof msg.system_data === 'string' ? JSON.parse(msg.system_data) : msg.system_data;
                    rotationId = data.rotation_id;
                } catch(e) {}
            }
            if (!rotationId) continue;

            if (!rotations[rotationId]) {
                rotations[rotationId] = [];
            }
            rotations[rotationId].push(msg);
        }

        for (const [rotationId, msgs] of Object.entries(rotations)) {
            const statuses = msgs.map(m => {
                let type = m.system_type?.toUpperCase() || '';
                if (type === 'ROTATION_REQUEST') return 'REQUEST';
                if (type === 'ROTATION_ACCEPT') return 'ACCEPT';
                if (type === 'ROTATION_CONFIRM') return 'CONFIRM';
                if (type === 'ROTATION_COMPLETE') return 'COMPLETE';
                if (type === 'ROTATION_REJECT') return 'REJECT';
                if (type === 'ROTATION_TIMEOUT') return 'TIMEOUT';
                return type;
            });

            if (statuses.includes('COMPLETE') || statuses.includes('REJECT') || statuses.includes('TIMEOUT')) {
                continue;
            }

            const sorted = [...msgs].sort((a, b) => b.timestamp - a.timestamp);
            const lastMsg = sorted[0];

            let type = lastMsg.system_type?.toUpperCase() || '';
            if (type === 'ROTATION_REQUEST') type = 'REQUEST';
            if (type === 'ROTATION_ACCEPT') type = 'ACCEPT';
            if (type === 'ROTATION_CONFIRM') type = 'CONFIRM';

            let systemData = lastMsg.system_data || {};
            if (typeof systemData === 'string') {
                try { systemData = JSON.parse(systemData); } catch(e) {}
            }

            const amIInitiator = lastMsg.from_id === this.core.currentUserId;
            const expiresAt = systemData.expires_at;

            if (expiresAt && this.isExpired(expiresAt)) {
                console.log(`[Rotation] Rotation ${rotationId} expired, skipping`);
                continue;
            }

            console.log(`[Rotation] Found active rotation: ${rotationId}, status=${type}, amIInitiator=${amIInitiator}`);

            if (type === 'REQUEST') {
                if (!amIInitiator) {
                    this._pendingRequest = {
                        rotationId: rotationId,
                        ephPublicKey: systemData.eph_public_key,
                        expiresAt: expiresAt
                    };
                    this.isPending = true;
                    this.currentRotationId = rotationId;
                    this.currentStatus = 'PENDING_REQUEST';
                    this.currentExpiresAt = expiresAt;
                    this._peerEphPublicKey = systemData.eph_public_key;

                    const savedKey = this._loadEphPrivateKey(rotationId);
                    if (savedKey) {
                        console.log(`[Rotation] Found saved ephPrivateKey for ${rotationId}, restoring ACCEPT state`);
                        this._pendingEphPrivateKey = savedKey;
                        const keyPair = this._keyPairFromPrivateKey(savedKey);
                        if (keyPair) {
                            this._pendingEphPublicKey = this._publicKeyToHex(keyPair.publicKey);
                        }
                        this.currentStatus = 'ACCEPT';
                    }

                    this._updateButtonState();
                    return true;
                } else {
                    const savedKey = this._loadEphPrivateKey(rotationId);
                    if (savedKey) {
                        console.log(`[Rotation] Restored initiator state for ${rotationId}`);
                        this.isPending = true;
                        this.currentRotationId = rotationId;
                        this.currentStatus = 'REQUEST';
                        this.currentExpiresAt = expiresAt;
                        this._pendingEphPrivateKey = savedKey;
                        const keyPair = this._keyPairFromPrivateKey(savedKey);
                        if (keyPair) {
                            this._pendingEphPublicKey = this._publicKeyToHex(keyPair.publicKey);
                        }
                        this._peerEphPublicKey = null;
                        this._updateButtonState();
                        return true;
                    }
                }
            }

            if (type === 'ACCEPT' && amIInitiator) {
                const savedKey = this._loadEphPrivateKey(rotationId);
                if (savedKey) {
                    console.log(`[Rotation] Restored initiator state with ACCEPT for ${rotationId}`);
                    this.isPending = true;
                    this.currentRotationId = rotationId;
                    this.currentStatus = 'REQUEST';
                    this.currentExpiresAt = expiresAt;
                    this._pendingEphPrivateKey = savedKey;
                    this._peerEphPublicKey = systemData.eph_public_key;
                    await this.processAccept(rotationId, systemData.eph_public_key);
                    return true;
                }
            }

            if (type === 'CONFIRM' && !amIInitiator) {
                const savedKey = this._loadEphPrivateKey(rotationId);
                if (savedKey) {
                    console.log(`[Rotation] Restored responder state with CONFIRM for ${rotationId}`);
                    this.isPending = true;
                    this.currentRotationId = rotationId;
                    this.currentStatus = 'ACCEPT';
                    this.currentExpiresAt = expiresAt;
                    this._pendingEphPrivateKey = savedKey;
                    await this.processConfirm(rotationId);
                    return true;
                }
            }
        }

        return false;
    }

    _keyPairFromPrivateKey(privateKeyHex) {
        try {
            const privateKeyBytes = this._hexToUint8Array(privateKeyHex);
            const publicKey = nacl.scalarMult.base(privateKeyBytes);
            return { publicKey: publicKey, secretKey: privateKeyBytes };
        } catch (e) {
            console.error('[Rotation] Failed to reconstruct key pair:', e);
            return null;
        }
    }

    _activateNewKey(newSessionKey) {
        if (!this.core.activeKeys) {
            this.core.activeKeys = {
                old: this.core.sessionKeyHex,
                new: null
            };
        }

        this.core.sessionKeyHex = newSessionKey;
        this.core.activeKeys.new = newSessionKey;

        DuoNetCrypto.storeSessionKey(this.core.dialogId, newSessionKey);

        console.log('[Rotation] New key activated, old key preserved for compatibility');

        // Refresh message decryption with new key
        setTimeout(() => this.core.refreshMessagesDecryption(), 500);
    }

    _finalizeRotation() {
        // НЕ удаляем old ключ мгновенно, а оставляем его на переходный период
        // Ключ будет очищен после N сообщений или по таймауту
        this.core.transitionWindowStart = Date.now();
        this.core.transitionMsgCounter = 0;
        this.core.transitionMaxMessages = 50; // Максимум сообщений в переходном окне
        this.core.isInTransition = true;

        this._clearEphPrivateKey();

        console.log('[Rotation] Transition window opened. Old key preserved for compatibility');
        DuoNetUI.showToast('🔄 Переходный период: старые ключи сохраняются', 'info');
    }

    init() {
        if (this._initialized) return;
        this._initialized = true;
        this._updateButtonState();
        this._cleanupExpiredKeys();
    }

    _updateButtonState() {
        const btn = document.getElementById('rotateKeyBtn');
        if (!btn) return;
        btn.disabled = this.isPending;
        btn.textContent = this.isPending ? '⏳ Waiting...' : '🔄 Update key';
    }

    _generateRotationId() {
        const date = new Date();
        const dateStr = date.toISOString().slice(0, 10).replace(/-/g, '');
        const randomPart = Math.random().toString(36).substring(2, 14);
        return `${dateStr}_${randomPart}`;
    }

    async _sendSystemMessage(subtype, data) {
        if (!this.core.ws || !this.core.ws.isConnected()) {
            console.error(`[Rotation] WebSocket not connected, cannot send ${subtype}`);
            DuoNetUI.showToast('WebSocket not connected', 'error');
            return false;
        }

        if (!this.core.wsReady) {
            console.log(`[Rotation] WebSocket not ready yet, waiting...`);
            await new Promise(resolve => setTimeout(resolve, 2000));
            if (!this.core.ws || !this.core.ws.isConnected() || !this.core.wsReady) {
                console.error(`[Rotation] WebSocket still not ready, aborting ${subtype}`);
                DuoNetUI.showToast('Connection not ready', 'error');
                return false;
            }
        }

        const messageId = DuoNetCrypto.generateMessageId();
        const timestamp = Math.floor(Date.now() / 1000);

        const systemMessage = {
            __type: "system",
            subtype: subtype,
            rotation_id: data.rotation_id,
            timestamp: timestamp,
            ...data
        };

        const plaintext = JSON.stringify(systemMessage);
        const phrase = null;
        const hasPhrase = false;

        console.log(`[Rotation] Sending ${subtype} for rotation ${data.rotation_id}`);

        try {
            const encrypted = await this.core.crypto.encrypt(
                plaintext,
                this.core.sessionKeyHex,
                this.core.currentUserId,
                this.core.contactId,
                phrase
            );

            this.core.ws.sendChatMessage(
                messageId,
                encrypted,
                this.core.sessionKeyHex,
                hasPhrase,
                plaintext
            );
            return true;
        } catch (error) {
            console.error(`[Rotation] Failed to send ${subtype}:`, error);
            return false;
        }
    }

    _generateECDHKeyPair() {
        const keyPair = nacl.box.keyPair();
        return keyPair;
    }

    _publicKeyToHex(publicKey) {
        return Array.from(publicKey).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    _privateKeyToHex(secretKey) {
        return Array.from(secretKey).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    _hexToUint8Array(hex) {
        const bytes = new Uint8Array(hex.length / 2);
        for (let i = 0; i < hex.length; i += 2) {
            bytes[i / 2] = parseInt(hex.substr(i, 2), 16);
        }
        return bytes;
    }

    _computeSharedSecret(mySecretKeyHex, peerPublicKeyHex) {
        const mySecretKey = this._hexToUint8Array(mySecretKeyHex);
        const peerPublicKey = this._hexToUint8Array(peerPublicKeyHex);
        const sharedSecret = nacl.scalarMult(mySecretKey, peerPublicKey);
        return sharedSecret;
    }

    async _deriveNewKey(sharedSecret, rotationId) {
        const encoder = new TextEncoder();
        const salt = encoder.encode(`duonet_rotation_v4:${rotationId}`);

        const keyMaterial = await crypto.subtle.importKey(
            "raw",
            sharedSecret,
            { name: "HKDF" },
            false,
            ["deriveKey"]
        );

        const newKey = await crypto.subtle.deriveKey(
            {
                name: "HKDF",
                salt: salt,
                info: encoder.encode("session_key"),
                hash: "SHA-256"
            },
            keyMaterial,
            { name: "AES-GCM", length: 256 },
            true,
            ["encrypt", "decrypt"]
        );

        const rawKey = await crypto.subtle.exportKey("raw", newKey);
        return Array.from(new Uint8Array(rawKey)).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    async initiate() {
        if (this.isPending) {
            DuoNetUI.showToast('Key rotation already in progress', 'info');
            return false;
        }

        DuoNetUI.showToast('Generating encryption keys...', 'info');

        try {
            const keyPair = this._generateECDHKeyPair();
            const ephPublicKeyHex = this._publicKeyToHex(keyPair.publicKey);
            const ephPrivateKeyHex = this._privateKeyToHex(keyPair.secretKey);

            const rotationId = this._generateRotationId();
            const expiresAt = Date.now() + (24 * 60 * 60 * 1000);

            this.isPending = true;
            this.currentRotationId = rotationId;
            this.currentStatus = 'REQUEST';
            this.currentExpiresAt = expiresAt / 1000;
            this._pendingEphPrivateKey = ephPrivateKeyHex;
            this._pendingEphPublicKey = ephPublicKeyHex;
            this._peerEphPublicKey = null;
            this._newSessionKey = null;
            this._pendingRequest = null;

            this._updateButtonState();
            this._saveEphPrivateKey(rotationId, ephPrivateKeyHex, expiresAt / 1000);

            const success = await this._sendSystemMessage('rotation_request', {
                rotation_id: rotationId,
                eph_public_key: ephPublicKeyHex,
                expires_at: Math.floor(expiresAt / 1000)
            });

            if (success) {
                DuoNetUI.showToast('✅ Key rotation request sent', 'success');

                if (this.core.system) {
                    this.core.system.addToUI({
                        id: 'temp_' + Date.now(),
                        from_id: this.core.currentUserId,
                        timestamp: Math.floor(Date.now() / 1000),
                        system_type: 'ROTATION_REQUEST',
                        system_data: {
                            rotation_id: rotationId,
                            eph_public_key: ephPublicKeyHex,
                            expires_at: Math.floor(expiresAt / 1000)
                        },
                        rotation_id: rotationId,
                        expires_at: Math.floor(expiresAt / 1000),
                        eph_public_key: ephPublicKeyHex
                    });
                }
            } else {
                this._resetRotation();
                DuoNetUI.showToast('❌ Failed to send rotation request', 'error');
            }

            return success;
        } catch (error) {
            console.error('Initiate rotation error:', error);
            this._resetRotation();
            DuoNetUI.showToast('❌ Error: ' + error.message, 'error');
            return false;
        }
    }

    async processIncomingRequest(rotationId, ephPublicKeyHex, expiresAt) {
        console.log(`[Rotation] processIncomingRequest:`, { rotationId, expiresAt });

        if (this.core.messages && this.core.messages.isRotationResolved(rotationId)) {
            console.log(`[Rotation] Request ${rotationId} already resolved, ignoring`);
            return;
        }

        if (this.isExpired(expiresAt)) {
            console.log(`[Rotation] Request ${rotationId} already expired, ignoring`);
            return;
        }

        const savedKey = this._loadEphPrivateKey(rotationId);
        if (savedKey) {
            console.log(`[Rotation] Already have saved key for ${rotationId}, not showing buttons again`);
            return;
        }

        this._pendingRequest = {
            rotationId: rotationId,
            ephPublicKey: ephPublicKeyHex,
            expiresAt: expiresAt
        };

        this.isPending = true;
        this.currentRotationId = rotationId;
        this.currentStatus = 'PENDING_REQUEST';
        this.currentExpiresAt = expiresAt;
        this._peerEphPublicKey = ephPublicKeyHex;

        this._updateButtonState();
        console.log(`[Rotation] Pending request stored for ${rotationId}`);
    }

    async accept(rotationId) {
        console.log(`[Rotation] accept: ${rotationId}`);

        if (this.core.messages && this.core.messages.isRotationResolved(rotationId)) {
            DuoNetUI.showToast('This request has already been processed', 'warning');
            return false;
        }

        if (!this._pendingRequest || this._pendingRequest.rotationId !== rotationId) {
            DuoNetUI.showToast('No pending rotation request', 'error');
            return false;
        }

        if (this.isExpired(this._pendingRequest.expiresAt)) {
            DuoNetUI.showToast('⏰ Rotation request expired', 'warning');
            this._pendingRequest = null;
            this._resetRotation();
            return false;
        }

        DuoNetUI.showToast('Generating new session key...', 'info');

        try {
            const keyPair = this._generateECDHKeyPair();
            const ephPublicKeyHex = this._publicKeyToHex(keyPair.publicKey);
            const ephPrivateKeyHex = this._privateKeyToHex(keyPair.secretKey);

            const sharedSecret = this._computeSharedSecret(
                ephPrivateKeyHex,
                this._pendingRequest.ephPublicKey
            );

            const newSessionKey = await this._deriveNewKey(sharedSecret, rotationId);

            this._saveEphPrivateKey(rotationId, ephPrivateKeyHex, this._pendingRequest.expiresAt);

            this.isPending = true;
            this.currentRotationId = rotationId;
            this.currentStatus = 'ACCEPT';
            this.currentExpiresAt = this._pendingRequest.expiresAt;
            this._pendingEphPrivateKey = ephPrivateKeyHex;
            this._pendingEphPublicKey = ephPublicKeyHex;
            this._peerEphPublicKey = this._pendingRequest.ephPublicKey;
            this._newSessionKey = newSessionKey;

            this._updateButtonState();

            const success = await this._sendSystemMessage('rotation_accept', {
                rotation_id: rotationId,
                eph_public_key: ephPublicKeyHex
            });

            if (success) {
                DuoNetUI.showToast('✅ Rotation accepted', 'success');
                this._removeRequestButtons(rotationId);
                this._activateNewKey(newSessionKey);
            }

            this._pendingRequest = null;
            return success;
        } catch (error) {
            console.error('Accept error:', error);
            this._resetRotation();
            DuoNetUI.showToast('❌ Error: ' + error.message, 'error');
            return false;
        }
    }

    async reject(rotationId) {
        console.log(`[Rotation] reject: ${rotationId}`);

        if (this.core.messages && this.core.messages.isRotationResolved(rotationId)) {
            DuoNetUI.showToast('This request has already been processed', 'warning');
            return false;
        }

        if (!this._pendingRequest || this._pendingRequest.rotationId !== rotationId) {
            DuoNetUI.showToast('No pending rotation request', 'error');
            return false;
        }

        const success = await this._sendSystemMessage('rotation_reject', {
            rotation_id: rotationId
        });

        if (success) {
            DuoNetUI.showToast('❌ Rotation rejected', 'info');
            this._removeRequestButtons(rotationId);
        }

        this._pendingRequest = null;
        this._resetRotation();
        return success;
    }

    async processAccept(rotationId, ephPublicKeyHex) {
        console.log(`[Rotation] processAccept: ${rotationId}`);

        const savedKey = this._loadEphPrivateKey(rotationId);
        if (!savedKey) {
            console.log(`[Rotation] No saved key for ${rotationId}, cannot process ACCEPT`);
            return;
        }

        if (this.currentRotationId !== rotationId) {
            this.isPending = true;
            this.currentRotationId = rotationId;
            this.currentStatus = 'REQUEST';
            this._pendingEphPrivateKey = savedKey;
            const keyPair = this._keyPairFromPrivateKey(savedKey);
            if (keyPair) {
                this._pendingEphPublicKey = this._publicKeyToHex(keyPair.publicKey);
            }
        }

        if (this.currentStatus !== 'REQUEST') {
            console.log(`[Rotation] Cannot process ACCEPT: current status ${this.currentStatus}, expected REQUEST`);
            return;
        }

        try {
            const sharedSecret = this._computeSharedSecret(
                this._pendingEphPrivateKey,
                ephPublicKeyHex
            );

            const newSessionKey = await this._deriveNewKey(sharedSecret, rotationId);

            this._peerEphPublicKey = ephPublicKeyHex;
            this._newSessionKey = newSessionKey;
            this.currentStatus = 'CONFIRM';

            this._activateNewKey(newSessionKey);

            await this._sendSystemMessage('rotation_confirm', {
                rotation_id: rotationId
            });

            DuoNetUI.showToast('🔐 Key rotation confirmed', 'success');
        } catch (error) {
            console.error('Process accept error:', error);
            DuoNetUI.showToast('❌ Error processing accept', 'error');
        }
    }

    async processConfirm(rotationId) {
        console.log(`[Rotation] processConfirm: ${rotationId}`);

        const savedKey = this._loadEphPrivateKey(rotationId);
        if (!savedKey) {
            console.log(`[Rotation] No saved key for ${rotationId}, cannot process CONFIRM`);
            return;
        }

        if (this.currentRotationId !== rotationId) {
            this.isPending = true;
            this.currentRotationId = rotationId;
            this.currentStatus = 'ACCEPT';
            this._pendingEphPrivateKey = savedKey;
        }

        if (this.currentStatus !== 'ACCEPT') {
            console.log(`[Rotation] Cannot process CONFIRM: current status ${this.currentStatus}, expected ACCEPT`);
            return;
        }

        this.currentStatus = 'COMPLETE';

        await this._sendSystemMessage('rotation_complete', {
            rotation_id: rotationId
        });

        this._completeRotation(rotationId);
    }

    async processComplete(rotationId) {
        console.log(`[Rotation] processComplete: ${rotationId}`);

        if (this.currentRotationId !== rotationId) {
            const savedKey = this._loadEphPrivateKey(rotationId);
            if (savedKey) {
                console.log(`[Rotation] Found saved key for completed rotation ${rotationId}, cleaning up`);
            }
        }

        this._completeRotation(rotationId);

        // !!! ДОБАВИТЬ ЭТОТ БЛОК !!!
        // Принудительно перезагружаем сообщения после завершения ротации
        setTimeout(() => {
            if (this.core && this.core.messages) {
                console.log('[Rotation] Reloading messages after rotation complete');
                this.core.messages.loadMessages(true);
            }
        }, 100);
    }

    async processReject(rotationId) {
        console.log(`[Rotation] processReject: ${rotationId}`);
        DuoNetUI.showToast('❌ Key rotation was rejected by peer', 'warning');
        this._resetRotation();
    }

    async processTimeout(rotationId) {
        console.log(`[Rotation] processTimeout: ${rotationId}`);
        DuoNetUI.showToast('⏰ Key rotation request expired', 'warning');
        this._resetRotation();

        if (this.core.messages) {
            setTimeout(() => this.core.messages.loadMessages(true), 500);
        }
    }

    _completeRotation(rotationId) {
        console.log(`[Rotation] _completeRotation: ${rotationId}`);
        this.isPending = false;
        this.currentRotationId = null;
        this.currentStatus = null;
        this.currentExpiresAt = null;
        this._pendingEphPrivateKey = null;
        this._pendingEphPublicKey = null;
        this._peerEphPublicKey = null;
        this._newSessionKey = null;
        this._pendingRequest = null;
        // НЕ вызываем _finalizeRotation() здесь, чтобы не обнулять old ключ
        // Очистка произойдет позже через _cleanupTransitionWindow
        this._updateButtonState();
        DuoNetUI.showToast('🔐 Key rotation completed successfully', 'success');
        if (this.core.messages) {
            setTimeout(() => this.core.messages.loadMessages(true), 500);
        }
    }

    _resetRotation() {
        console.log('[Rotation] _resetRotation');
        this.isPending = false;
        this.currentRotationId = null;
        this.currentStatus = null;
        this.currentExpiresAt = null;
        this._pendingEphPrivateKey = null;
        this._pendingEphPublicKey = null;
        this._peerEphPublicKey = null;
        this._newSessionKey = null;
        this._pendingRequest = null;
        this._clearEphPrivateKey();
        this._updateButtonState();
    }

    _removeRequestButtons(rotationId) {
        const messages = document.querySelectorAll('.system-message');
        for (const msg of messages) {
            const buttons = msg.querySelector('.rotation-buttons');
            if (buttons && msg.textContent.includes(rotationId)) {
                buttons.remove();
                if (!msg.querySelector('.processed-status')) {
                    const statusSpan = document.createElement('span');
                    statusSpan.textContent = ' ✓ Processed';
                    statusSpan.className = 'processed-status';
                    statusSpan.style.color = '#4caf50';
                    statusSpan.style.marginLeft = '8px';
                    statusSpan.style.fontSize = '11px';
                    const firstDiv = msg.querySelector('div:first-child');
                    if (firstDiv) {
                        firstDiv.appendChild(statusSpan);
                    }
                }
            }
        }
    }

    /**
    * Cleans up transition window when expired or message limit reached
    */
    _cleanupTransitionWindow() {
        if (!this.core.isInTransition) return;

        const expired = Date.now() - this.core.transitionWindowStart > 3600 * 1000; // 1 час
        const counted = this.core.transitionMsgCounter >= this.core.transitionMaxMessages;

        if (expired || counted) {
            this.core.activeKeys.old = null;
            this.core.activeKeys.new = null;
            this.core.isInTransition = false;
            console.log('[Rotation] Transition window closed. Old keys purged');
        }
    }

    destroy() {
        this._initialized = false;
    }
}

window.DuoNetRotation = DuoNetRotation;
