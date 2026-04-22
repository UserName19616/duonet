/**
 * DuoNet Crypto Module
 * Client-side cryptography for end-to-end encryption
 * Implements LRP (Lottery Ratchet Protocol) with key pool,
 * directional keys, phrase protection, and AES-256-GCM
 */

class DuoNetCrypto {
    // =========================================================================
    // LRP Key Pool (Lottery Ratchet Protocol)
    // =========================================================================

    /**
     * Generate deterministic key pool from session key
     * Both sides generate the SAME pool independently (no server involved!)
     * @param {string} sessionKeyHex - 32-byte session key in hex
     * @param {string} fromId - Sender's Public ID
     * @param {string} toId - Receiver's Public ID
     * @param {number} poolSize - Size of key pool (default 16)
     * @returns {Promise<Array<string>>} Array of 16 keys in hex
     */
    static async generateKeyPool(sessionKeyHex, fromId, toId, poolSize = 16) {
        console.log('[Crypto] generateKeyPool:', {
            sessionKeyHex: sessionKeyHex?.substring(0, 20),
            fromId,
            toId
        });
        const pool = [];
        const encoder = new TextEncoder();

        // Create base seed: session key + dialog salt
        const dialogId = fromId < toId ? `${fromId}:${toId}` : `${toId}:${fromId}`;
        const dialogSalt = encoder.encode(dialogId);

        // Import session key as HMAC key for HKDF
        const keyBytes = new Uint8Array(sessionKeyHex.match(/.{1,2}/g).map(b => parseInt(b, 16)));
        const baseKey = await crypto.subtle.importKey(
            "raw",
            keyBytes,
            { name: "HMAC", hash: "SHA-256" },
            false,
            ["sign"]
        );

        for (let i = 0; i < poolSize; i++) {
            // HKDF: extract then expand
            const info = encoder.encode(`lottery_key_${i}_v2`);

            // HKDF-Expand
            const hmacKey = await crypto.subtle.importKey(
                "raw",
                keyBytes,
                { name: "HMAC", hash: "SHA-256" },
                false,
                ["sign"]
            );

            const signature = await crypto.subtle.sign(
                "HMAC",
                hmacKey,
                this.concatArrays(dialogSalt, info)
            );

            // Take first 32 bytes as pool key
            const poolKey = new Uint8Array(signature).slice(0, 32);
            const poolKeyHex = Array.from(poolKey).map(b => b.toString(16).padStart(2, '0')).join('');
            pool.push(poolKeyHex);
        }

        console.log('[Crypto] pool[0-2]:', pool.slice(0, 3).map(k => k.substring(0, 20)));
        return pool;
    }

    /**
     * Concatenate Uint8Arrays
     * @private
     */
    static concatArrays(a, b) {
        const result = new Uint8Array(a.length + b.length);
        result.set(a, 0);
        result.set(b, a.length);
        return result;
    }

    /**
     * Get directional key for specific direction (A→B or B→A)
     * @param {string} keyHex - 32-byte key (can be session key or pool key) in hex
     * @param {string} fromId - Sender's Public ID
     * @param {string} toId - Receiver's Public ID
     * @returns {Promise<string>} 32-byte directional key in hex
     */
    static async getDirectionalKey(keyHex, fromId, toId) {
        const encoder = new TextEncoder();
        const directionStr = `${fromId}:${toId}`;
        const keyBytes = new Uint8Array(keyHex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));

        const cryptoKey = await crypto.subtle.importKey(
            "raw",
            keyBytes,
            { name: "HMAC", hash: "SHA-256" },
            false,
            ["sign"]
        );

        const signature = await crypto.subtle.sign("HMAC", cryptoKey, encoder.encode(directionStr));
        const directionalKey = new Uint8Array(signature).slice(0, 32);

        return Array.from(directionalKey).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    /**
     * Derive key from secret phrase using SHA-256
     * @param {string} phrase - Secret phrase
     * @returns {Promise<string>} 32-byte phrase key in hex
     */
    static async getPhraseKey(phrase) {
        const encoder = new TextEncoder();
        const data = encoder.encode(phrase);
        const hashBuffer = await crypto.subtle.digest('SHA-256', data);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    }

    /**
     * XOR two hex strings of equal length
     * @param {string} key1Hex - First key in hex
     * @param {string} key2Hex - Second key in hex
     * @returns {string} XOR result in hex
     */
    static xorKeys(key1Hex, key2Hex) {
        const key1 = new Uint8Array(key1Hex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
        const key2 = new Uint8Array(key2Hex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
        const result = new Uint8Array(32);
        for (let i = 0; i < 32; i++) {
            result[i] = key1[i] ^ key2[i];
        }
        return Array.from(result).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    /**
     * Encrypt message using AES-256-GCM
     * @param {string} plaintext - Message to encrypt
     * @param {string} keyHex - 32-byte encryption key in hex
     * @returns {Promise<string>} Ciphertext in hex (nonce + encrypted data)
     */
    static async encryptMessage(plaintext, keyHex) {
        const encoder = new TextEncoder();
        const data = encoder.encode(plaintext);
        const keyBytes = new Uint8Array(keyHex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));

        const iv = crypto.getRandomValues(new Uint8Array(12));

        const cryptoKey = await crypto.subtle.importKey(
            "raw",
            keyBytes,
            "AES-GCM",
            false,
            ["encrypt"]
        );

        const encrypted = await crypto.subtle.encrypt(
            { name: "AES-GCM", iv: iv },
            cryptoKey,
            data
        );

        const result = new Uint8Array(iv.length + encrypted.byteLength);
        result.set(iv, 0);
        result.set(new Uint8Array(encrypted), iv.length);

        return Array.from(result).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    /**
     * Decrypt message using AES-256-GCM
     * @param {string} ciphertextHex - Ciphertext in hex (nonce + encrypted data)
     * @param {string} keyHex - 32-byte encryption key in hex
     * @returns {Promise<string|null>} Decrypted plaintext or null on failure
     */
    static async decryptMessage(ciphertextHex, keyHex) {
        if (!ciphertextHex || !keyHex) return null;

        try {
            const ciphertext = new Uint8Array(ciphertextHex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
            const keyBytes = new Uint8Array(keyHex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));

            const iv = ciphertext.slice(0, 12);
            const data = ciphertext.slice(12);

            const cryptoKey = await crypto.subtle.importKey(
                "raw",
                keyBytes,
                "AES-GCM",
                false,
                ["decrypt"]
            );

            const decrypted = await crypto.subtle.decrypt(
                { name: "AES-GCM", iv: iv },
                cryptoKey,
                data
            );
            return new TextDecoder().decode(decrypted);
        } catch (e) {
            return null;
        }
    }

    // =========================================================================
    // High-level LRP Encryption/Decryption with Key Pool
    // =========================================================================

    /**
     * LRP Encryption: randomly selects a key from the pool
     * @param {string} plaintext - Message to encrypt
     * @param {string} sessionKeyHex - Session key in hex
     * @param {string} fromId - Sender's Public ID
     * @param {string} toId - Receiver's Public ID
     * @param {string|null} phrase - Optional secret phrase
     * @returns {Promise<{ciphertext: string, keyIndex: number, poolSize: number}>}
     */
    async encryptLRP(plaintext, sessionKeyHex, fromId, toId, phrase = null) {
        // 1. Generate key pool (deterministic, same on both sides)
        const pool = await DuoNetCrypto.generateKeyPool(sessionKeyHex, fromId, toId, 16);

        // 2. Randomly select a key from pool (0-15)
        const keyIndex = Math.floor(Math.random() * 16);
        const poolKeyHex = pool[keyIndex];

        // 3. Get directional key from pool key
        let key = await DuoNetCrypto.getDirectionalKey(poolKeyHex, fromId, toId);

        // 4. Apply phrase if provided
        if (phrase) {
            const phraseKeyHex = await DuoNetCrypto.getPhraseKey(phrase);
            key = DuoNetCrypto.xorKeys(key, phraseKeyHex);
        }

        // 5. Encrypt message
        const ciphertext = await DuoNetCrypto.encryptMessage(plaintext, key);

        // 6. Return ciphertext WITH keyIndex (for header)
        // Format: [keyIndex:1 byte][ciphertext]
        const keyIndexByte = new Uint8Array([keyIndex]);
        const ciphertextBytes = new Uint8Array(ciphertext.match(/.{1,2}/g).map(b => parseInt(b, 16)));
        const result = new Uint8Array(1 + ciphertextBytes.length);
        result.set(keyIndexByte, 0);
        result.set(ciphertextBytes, 1);

        return {
            ciphertext: Array.from(result).map(b => b.toString(16).padStart(2, '0')).join(''),
            keyIndex: keyIndex,
            poolSize: 16
        };
    }

    /**
     * LRP Decryption: uses keyIndex to select the correct key from pool
     * @param {string} ciphertextWithIndexHex - Ciphertext with prepended keyIndex (1 byte)
     * @param {string} sessionKeyHex - Session key in hex
     * @param {string} fromId - Sender's Public ID
     * @param {string} toId - Receiver's Public ID
     * @param {string|null} phrase - Optional secret phrase
     * @returns {Promise<string|null>} Decrypted plaintext or null
     */
    async decryptLRP(ciphertextWithIndexHex, sessionKeyHex, fromId, toId, phrase = null) {
        try {
            const data = new Uint8Array(ciphertextWithIndexHex.match(/.{1,2}/g).map(b => parseInt(b, 16)));
            if (data.length < 1) return null;

            const keyIndex = data[0];
            const ciphertextHex = Array.from(data.slice(1)).map(b => b.toString(16).padStart(2, '0')).join('');

            const pool = await DuoNetCrypto.generateKeyPool(sessionKeyHex, fromId, toId, 16);

            console.log('[Crypto] decryptLRP:', {
                keyIndex,
                poolKeyHex: pool[keyIndex]?.substring(0, 20),
                poolSize: pool.length,
                fromId,
                toId
            });

            if (keyIndex >= pool.length) return null;
            const poolKeyHex = pool[keyIndex];

            let key = await DuoNetCrypto.getDirectionalKey(poolKeyHex, fromId, toId);

            if (phrase) {
                const phraseKeyHex = await DuoNetCrypto.getPhraseKey(phrase);
                key = DuoNetCrypto.xorKeys(key, phraseKeyHex);
            }

            const decrypted = await DuoNetCrypto.decryptMessage(ciphertextHex, key);
            if (decrypted) {
                console.log('[Crypto] decryptLRP SUCCESS');
            }
            return decrypted;
        } catch (e) {
            console.error('[Crypto] decryptLRP error:', e);
            return null;
        }
    }

    /**
     * Simple encryption (without LRP pool) - for backward compatibility
     * @param {string} plaintext - Message to encrypt
     * @param {string} sessionKeyHex - Session key in hex
     * @param {string} fromId - Sender's Public ID
     * @param {string} toId - Receiver's Public ID
     * @param {string|null} phrase - Optional secret phrase
     * @returns {Promise<string>} Ciphertext in hex
     */
    async encrypt(plaintext, sessionKeyHex, fromId, toId, phrase = null) {
        // Use LRP by default
        const result = await this.encryptLRP(plaintext, sessionKeyHex, fromId, toId, phrase);
        return result.ciphertext;
    }

    /**
     * Simple decryption (without LRP pool) - for backward compatibility
     * @param {string} ciphertextHex - Ciphertext in hex
     * @param {string} sessionKeyHex - Session key in hex
     * @param {string} fromId - Sender's Public ID
     * @param {string} toId - Receiver's Public ID
     * @param {string|null} phrase - Optional secret phrase
     * @returns {Promise<string|null>} Decrypted plaintext or null
     */
    async decrypt(ciphertextHex, sessionKeyHex, fromId, toId, phrase = null) {
        // Use LRP decryption
        return await this.decryptLRP(ciphertextHex, sessionKeyHex, fromId, toId, phrase);
    }

    /**
     * Generate random session key (32 bytes)
     * @returns {string} Session key in hex
     */
    static generateSessionKey() {
        const key = crypto.getRandomValues(new Uint8Array(32));
        return Array.from(key).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    // =========================================================================
    // Message ID Helpers
    // =========================================================================

    static generateMessageId(counter = 0) {
        const randomPart = Math.random().toString(36).substring(2, 14);
        const safeCounter = (counter && !isNaN(counter)) ? counter : 0;
        const counterHex = safeCounter.toString(16).padStart(4, '0');
        return `msg_${counterHex}_${randomPart}`;
    }

    static extractCounter(messageId) {
        if (!messageId || typeof messageId !== 'string') return 0;
        const match = messageId.match(/msg_([0-9a-f]{4})_/);
        if (match && match[1]) {
            return parseInt(match[1], 16);
        }
        return 0;
    }

    // =========================================================================
    // LocalStorage helpers
    // =========================================================================

    static storeSessionKey(dialogId, sessionKeyHex) {
        const stored = JSON.parse(localStorage.getItem('duonet_session_keys') || '{}');
        stored[dialogId] = sessionKeyHex;
        localStorage.setItem('duonet_session_keys', JSON.stringify(stored));
    }

    static getStoredSessionKey(dialogId) {
        const stored = JSON.parse(localStorage.getItem('duonet_session_keys') || '{}');
        return stored[dialogId] || null;
    }

    static storePhrase(contactId, phrase) {
        const stored = JSON.parse(localStorage.getItem('duonet_phrases') || '{}');
        stored[contactId] = phrase;
        localStorage.setItem('duonet_phrases', JSON.stringify(stored));
    }

    static getStoredPhrase(contactId) {
        const stored = JSON.parse(localStorage.getItem('duonet_phrases') || '{}');
        return stored[contactId] || null;
    }

    static clearStoredPhrase(contactId) {
        const stored = JSON.parse(localStorage.getItem('duonet_phrases') || '{}');
        delete stored[contactId];
        localStorage.setItem('duonet_phrases', JSON.stringify(stored));
    }

    // =========================================================================
    // Dual-key support for key rotation (used by DuoNetCore.decryptMessage)
    // =========================================================================

    /**
     * Try decrypting with both old and new keys during rotation transition period
     * @param {string} ciphertextHex - Ciphertext in hex (with keyIndex prefix)
     * @param {string} oldKeyHex - Old session key in hex
     * @param {string} newKeyHex - New session key in hex
     * @param {string} fromId - Sender's Public ID
     * @param {string} toId - Receiver's Public ID
     * @param {string|null} phrase - Optional secret phrase
     * @returns {Promise<string|null>} Decrypted plaintext or null
     */
    static async tryBothKeys(ciphertextHex, oldKeyHex, newKeyHex, fromId, toId, phrase) {
        // Create a temporary instance for method calls
        const tempInstance = new DuoNetCrypto();

        // First try new key
        if (newKeyHex) {
            const decrypted = await tempInstance.decryptLRP(
                ciphertextHex, newKeyHex, fromId, toId, phrase
            );
            if (decrypted !== null) return decrypted;
        }

        // Then try old key
        if (oldKeyHex) {
            const decrypted = await tempInstance.decryptLRP(
                ciphertextHex, oldKeyHex, fromId, toId, phrase
            );
            if (decrypted !== null) return decrypted;
        }

        return null;
    }
}

window.DuoNetCrypto = DuoNetCrypto;
