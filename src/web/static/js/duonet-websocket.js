/**
 * DuoNet WebSocket Module
 * WebSocket connection management with auto-reconnect and message handling
 * Includes fixed status and typing handlers, plus rotation_reject support
 */

class DuoNetWebSocket {
    /**
     * Create WebSocket manager
     * @param {string} url - WebSocket URL
     * @param {Object} handlers - Event handlers
     * @param {Function} handlers.onMessage - Message handler
     * @param {Function} handlers.onOpen - Connection open handler
     * @param {Function} handlers.onClose - Connection close handler
     * @param {Function} handlers.onError - Error handler
     * @param {Function} handlers.onStatusResponse - Status response handler
     * @param {Function} handlers.onTyping - Typing indicator handler
     * @param {Function} handlers.onRotationRequest - Rotation request handler
     * @param {Function} handlers.onRotationAck - Rotation ACK handler
     * @param {Function} handlers.onRotationReject - Rotation REJECT handler
     * @param {Object} options - Configuration options
     * @param {number} options.reconnectDelay - Reconnect delay in ms (default: 3000)
     * @param {number} options.maxReconnectAttempts - Max reconnect attempts (default: Infinity)
     */
    constructor(url, handlers = {}, options = {}) {
        this.url = url;
        this.handlers = handlers;
        this.reconnectDelay = options.reconnectDelay || 3000;
        this.maxReconnectAttempts = options.maxReconnectAttempts || Infinity;
        this.reconnectAttempts = 0;
        this.ws = null;
        this._isClosing = false;
        this._heartbeatInterval = null;
        this._heartbeatTimeout = options.heartbeatTimeout || 45000;
        this._lastPong = Date.now();
        this._lastSentType = null;
    }

    /**
     * Connect WebSocket
     * @returns {Promise<void>}
     */
    connect() {
        return new Promise((resolve, reject) => {
            try {
                console.log(`🔌 Connecting WebSocket: ${this.url}`);
                this.ws = new WebSocket(this.url);

                this.ws.onopen = (event) => {
                    console.log('✅ WebSocket connected');
                    this.reconnectAttempts = 0;
                    this._startHeartbeat();
                    if (this.handlers.onOpen) this.handlers.onOpen(event);
                    resolve();
                };

                this.ws.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        console.log('📨 WebSocket message received:', data.type);

                        if (data.type === 'status_response') {
                            console.log('Status response received:', data.data);
                            if (this.handlers.onStatusResponse) {
                                this.handlers.onStatusResponse(data.data);
                            }
                            return;
                        }

                        if (data.type === 'status') {
                            console.log('Status message:', data.data);
                            if (this.handlers.onStatus) {
                                this.handlers.onStatus(data.data);
                            }
                            return;
                        }

                        if (data.type === 'typing') {
                            if (this.handlers.onTyping) {
                                this.handlers.onTyping(data.data);
                            }
                            return;
                        }

                        if (data.type === 'rotation_request') {
                            if (this.handlers.onRotationRequest) {
                                this.handlers.onRotationRequest(data.data);
                            }
                            return;
                        }

                        if (data.type === 'rotation_ack') {
                            if (this.handlers.onRotationAck) {
                                this.handlers.onRotationAck(data.data);
                            }
                            return;
                        }

                        if (data.type === 'rotation_confirm') {
                            console.log('📨 Rotation confirm received:', data.data);
                            if (this.handlers.onRotationConfirm) {
                                this.handlers.onRotationConfirm(data.data);
                            }
                            return;
                        }

                        if (data.type === 'rotation_reject') {
                            console.log('📨 Rotation reject received:', data.data);
                            if (this.handlers.onRotationReject) {
                                this.handlers.onRotationReject(data.data);
                            }
                            return;
                        }

                        if (data.type === 'rotation_complete') {
                            console.log('📨 Rotation complete received:', data.data);
                            if (this.handlers.onRotationComplete) {
                                this.handlers.onRotationComplete(data.data);
                            }
                            return;
                        }

                        if (data.type === 'error') {
                            if (data.data && data.data.code === 'unknown_type' &&
                                this._lastSentType === 'status') {
                                console.log('⚠️ Ignored unknown_type error for status message');
                                return;
                            }
                            console.error('WebSocket error message:', data.data);
                            if (this.handlers.onError) {
                                this.handlers.onError(data.data);
                            }
                            return;
                        }

                        if (this.handlers.onMessage) {
                            this.handlers.onMessage(data);
                        }
                    } catch (e) {
                        console.error('Failed to parse WebSocket message:', e);
                        if (this.handlers.onError) this.handlers.onError(e);
                    }
                };

                this.ws.onclose = (event) => {
                    console.log(`🔌 WebSocket disconnected: code=${event.code}, reason=${event.reason}`);
                    this._stopHeartbeat();
                    if (this.handlers.onClose) this.handlers.onClose(event);

                    if (!this._isClosing) {
                        this._reconnect();
                    }
                };

                this.ws.onerror = (error) => {
                    console.error('❌ WebSocket error:', error);
                    if (this.handlers.onError) this.handlers.onError(error);
                    reject(error);
                };
            } catch (error) {
                console.error('Failed to create WebSocket:', error);
                reject(error);
            }
        });
    }

    /**
     * Send message through WebSocket
     * @param {Object} data - Message data (will be JSON stringified)
     * @returns {boolean} True if sent successfully
     */
    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this._lastSentType = data.type;
            const messageStr = JSON.stringify(data);
            console.log('📤 WebSocket sending:', data.type, messageStr);
            this.ws.send(messageStr);
            return true;
        }
        console.warn('WebSocket not open, cannot send message');
        return false;
    }

    /**
     * Send raw text through WebSocket
     * @param {string} text - Raw text to send
     * @returns {boolean} True if sent successfully
     */
    sendRaw(text) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(text);
            return true;
        }
        return false;
    }

    /**
     * Send typing indicator (FIXED - uses correct format)
     * @param {string} toId - Recipient Public ID
     * @param {boolean} isTyping - Whether user is typing
     * @returns {boolean} True if sent
     */
    sendTyping(toId, isTyping = true) {
        return this.send({
            type: 'typing',
            data: { to: toId, is_typing: isTyping }
        });
    }

    /**
     * Send status update (FIXED - uses correct format)
     * @param {boolean} online - Online status
     * @param {number} load - Server load (0-100)
     * @returns {boolean} True if sent
     */
    sendStatus(online = true, load = 0) {
        return this.send({
            type: 'status',
            data: { online: online, load: load }
        });
    }

    /**
     * Send rotation request
     * @param {string} toId - Recipient Public ID
     * @param {string} requestId - Unique request ID
     * @param {number} timestamp - Request timestamp
     * @returns {boolean} True if sent
     */
    sendRotationRequest(toId, requestId, timestamp) {
        return this.send({
            type: 'rotation_request',
            data: { to: toId, request_id: requestId, timestamp: timestamp }
        });
    }

    /**
     * Send rotation acknowledgement
     * @param {string} toId - Recipient Public ID
     * @param {string} requestId - Request ID being acknowledged
     * @returns {boolean} True if sent
     */
    sendRotationAck(toId, requestId) {
        return this.send({
            type: 'rotation_ack',
            data: { to: toId, request_id: requestId }
        });
    }

    /**
     * Send rotation confirm
     * @param {string} toId - Recipient Public ID
     * @param {string} requestId - Request ID being confirmed
     * @returns {boolean} True if sent
     */
    sendRotationConfirm(toId, requestId) {
        return this.send({
            type: 'rotation_confirm',
            data: { to: toId, request_id: requestId }
        });
    }

    /**
     * Send rotation rejection
     * @param {string} toId - Recipient Public ID
     * @param {string} requestId - Request ID being rejected
     * @param {number} rejectCount - Current reject count (1-3)
     * @param {number} blockedUntil - Timestamp when block ends (if blocked)
     * @returns {boolean} True if sent
     */
    sendRotationReject(toId, requestId, rejectCount, blockedUntil = 0) {
        return this.send({
            type: 'rotation_reject',
            data: {
                to: toId,
                request_id: requestId,
                reject_count: rejectCount,
                blocked_until: blockedUntil
            }
        });
    }

    /**
     * Send rotation complete
     * @param {string} toId - Recipient Public ID
     * @param {string} requestId - Request ID being completed
     * @returns {boolean} True if sent
     */
    sendRotationComplete(toId, requestId) {
        return this.send({
            type: 'rotation_complete',
            data: { to: toId, request_id: requestId }
        });
    }

    /**
     * Close WebSocket connection
     * @param {number} code - Close code
     * @param {string} reason - Close reason
     */
    close(code = 1000, reason = '') {
        this._isClosing = true;
        this._stopHeartbeat();
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.close(code, reason);
        }
        this.ws = null;
    }

    /**
     * Check if WebSocket is connected
     * @returns {boolean}
     */
    isConnected() {
        return this.ws && this.ws.readyState === WebSocket.OPEN;
    }

    /**
     * Get connection state
     * @returns {number} WebSocket readyState
     */
    getReadyState() {
        return this.ws ? this.ws.readyState : WebSocket.CLOSED;
    }

    /**
     * Attempt to reconnect
     * @private
     */
    _reconnect() {
        if (this._isClosing) return;

        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error('Max reconnect attempts reached');
            if (this.handlers.onError) {
                this.handlers.onError(new Error('Max reconnect attempts reached'));
            }
            return;
        }

        this.reconnectAttempts++;
        console.log(`Reconnecting in ${this.reconnectDelay}ms (attempt ${this.reconnectAttempts})`);

        setTimeout(() => {
            if (!this._isClosing) {
                this.connect().catch(console.error);
            }
        }, this.reconnectDelay);
    }

    /**
     * Start heartbeat to keep connection alive
     * @private
     */
    _startHeartbeat() {
        this._heartbeatInterval = setInterval(() => {
            if (this.isConnected()) {
                this.send({ type: 'ping' });
            }
        }, 30000);
    }

    /**
     * Stop heartbeat
     * @private
     */
    _stopHeartbeat() {
        if (this._heartbeatInterval) {
            clearInterval(this._heartbeatInterval);
            this._heartbeatInterval = null;
        }
    }

    /**
     * Update last pong time (call when receiving pong)
     */
    pong() {
        this._lastPong = Date.now();
    }
}

/**
 * Chat WebSocket wrapper with message queuing
 */
class DuoNetChatWebSocket extends DuoNetWebSocket {
    constructor(url, contactId, handlers = {}, options = {}) {
        super(url, handlers, options);
        this.contactId = contactId;
        console.log('DuoNetChatWebSocket created with contactId:', contactId);
        this._pendingMessages = [];
        this._isReady = false;
    }

    connect() {
        return super.connect().then(() => {
            this._isReady = true;
            this._flushPendingMessages();
            this.sendStatus(true);
        });
    }

    /**
     * Send chat message
     * @param {string} messageId - Message ID
     * @param {string} encrypted - Encrypted message in hex
     * @param {string} sessionKey - Session key in hex
     * @param {boolean} hasPhrase - Whether message has phrase protection
     * @param {string|null} plaintext - Plaintext (for own messages)
     * @returns {boolean} True if sent
     */
    sendChatMessage(messageId, encrypted, sessionKey, hasPhrase = false, plaintext = null) {
        if (!this.contactId) {
            console.error('sendChatMessage: contactId is missing!');
            return false;
        }

        const message = {
            type: 'message',
            to: this.contactId,
            data: {
                message_id: messageId,
                encrypted: encrypted,
                session_key: sessionKey,
                has_phrase: hasPhrase,
                plaintext: plaintext,
                is_file: false,
                file_size: null
            }
        };

        console.log('Sending message with to:', this.contactId);

        if (this.isConnected() && this._isReady) {
            return this.send(message);
        } else {
            this._pendingMessages.push(message);
            console.log(`Message queued (pending: ${this._pendingMessages.length})`);
            return false;
        }
    }

    /**
     * Send system message (rotation_request, rotation_ack, rotation_reject, rotation_confirm, rotation_complete)
     * @param {string} type - System message type
     * @param {Object} data - Message data
     * @returns {boolean} True if sent
     */
    sendSystemMessage(type, data) {
        const message = {
            type: type,
            to: this.contactId,
            data: data
        };

        if (this.isConnected() && this._isReady) {
            return this.send(message);
        } else {
            console.warn(`WebSocket not ready, cannot send system message: ${type}`);
            return false;
        }
    }

    /**
     * Flush pending messages
     * @private
     */
    _flushPendingMessages() {
        while (this._pendingMessages.length > 0) {
            const msg = this._pendingMessages.shift();
            this.send(msg);
        }
    }
}

// Export for use in other modules
window.DuoNetWebSocket = DuoNetWebSocket;
window.DuoNetChatWebSocket = DuoNetChatWebSocket;
