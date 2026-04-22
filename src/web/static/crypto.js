// src/web/static/crypto.js
// Клиентская криптография для DuoNet

class DuoNetCrypto {
    constructor() {
        this.sessionKeys = new Map(); // dialog_id -> session_key (hex string)
        this.phrases = new Map();     // contact_id -> phrase
    }

    // Генерация сессионного ключа (32 байта)
    static async generateSessionKey() {
        const key = crypto.getRandomValues(new Uint8Array(32));
        return Array.from(key).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    // Импорт публичного ключа из hex
    static async importPublicKey(publicKeyHex) {
        const keyData = new Uint8Array(publicKeyHex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
        return await crypto.subtle.importKey(
            "raw",
            keyData,
            { name: "RSA-OAEP", hash: "SHA-256" },
            false,
            ["encrypt"]
        );
    }

    // Шифрование session_key публичным ключом получателя
    static async encryptSessionKey(sessionKeyHex, recipientPublicKeyHex) {
        const publicKey = await this.importPublicKey(recipientPublicKeyHex);
        const sessionKeyBytes = new Uint8Array(sessionKeyHex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));

        const encrypted = await crypto.subtle.encrypt(
            { name: "RSA-OAEP" },
            publicKey,
            sessionKeyBytes
        );

        return Array.from(new Uint8Array(encrypted)).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    // Импорт приватного ключа (для расшифровки session_key)
    static async importPrivateKey(privateKeyHex) {
        const keyData = new Uint8Array(privateKeyHex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
        return await crypto.subtle.importKey(
            "pkcs8",
            keyData,
            { name: "RSA-OAEP", hash: "SHA-256" },
            false,
            ["decrypt"]
        );
    }

    // Расшифровка session_key приватным ключом
    static async decryptSessionKey(encryptedSessionKeyHex, privateKeyHex) {
        const privateKey = await this.importPrivateKey(privateKeyHex);
        const encryptedBytes = new Uint8Array(encryptedSessionKeyHex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));

        const decrypted = await crypto.subtle.decrypt(
            { name: "RSA-OAEP" },
            privateKey,
            encryptedBytes
        );

        return Array.from(new Uint8Array(decrypted)).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    // Получение направленного ключа (HMAC-SHA256)
    static async getDirectionalKey(sessionKeyHex, fromId, toId) {
        const encoder = new TextEncoder();
        const directionStr = `${fromId}:${toId}`;

        // Импортируем session_key как HMAC ключ
        const keyBytes = new Uint8Array(sessionKeyHex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
        const cryptoKey = await crypto.subtle.importKey(
            "raw",
            keyBytes,
            { name: "HMAC", hash: "SHA-256" },
            false,
            ["sign"]
        );

        const signature = await crypto.subtle.sign(
            "HMAC",
            cryptoKey,
            encoder.encode(directionStr)
        );

        // Берем первые 32 байта как направленный ключ
        const directionalKey = new Uint8Array(signature).slice(0, 32);
        return Array.from(directionalKey).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    // Получение ключа из фразы (PBKDF2)
    static async derivePhraseKey(phrase, saltHex) {
        const encoder = new TextEncoder();
        const salt = new Uint8Array(saltHex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));

        const keyMaterial = await crypto.subtle.importKey(
            "raw",
            encoder.encode(phrase),
            "PBKDF2",
            false,
            ["deriveKey"]
        );

        const key = await crypto.subtle.deriveKey(
            {
                name: "PBKDF2",
                salt: salt,
                iterations: 100000,
                hash: "SHA-256"
            },
            keyMaterial,
            { name: "AES-GCM", length: 256 },
            false,
            ["encrypt", "decrypt"]
        );

        // Экспортируем ключ как hex
        const rawKey = await crypto.subtle.exportKey("raw", key);
        return Array.from(new Uint8Array(rawKey)).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    // XOR двух hex ключей
    static xorKeys(key1Hex, key2Hex) {
        const key1 = new Uint8Array(key1Hex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
        const key2 = new Uint8Array(key2Hex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
        const result = new Uint8Array(32);
        for (let i = 0; i < 32; i++) {
            result[i] = key1[i] ^ key2[i];
        }
        return Array.from(result).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    // Шифрование сообщения (AES-GCM)
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

        // Формат: iv (12) + ciphertext
        const result = new Uint8Array(iv.length + encrypted.byteLength);
        result.set(iv, 0);
        result.set(new Uint8Array(encrypted), iv.length);

        return Array.from(result).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    // Расшифровка сообщения (AES-GCM)
    static async decryptMessage(ciphertextHex, keyHex) {
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

        try {
            const decrypted = await crypto.subtle.decrypt(
                { name: "AES-GCM", iv: iv },
                cryptoKey,
                data
            );
            const decoder = new TextDecoder();
            return decoder.decode(decrypted);
        } catch (e) {
            console.error("Decryption failed:", e);
            return null;
        }
    }

    // Полный цикл шифрования с направлением и фразой
    async encrypt(plaintext, sessionKeyHex, fromId, toId, phrase = null) {
        // 1. Получаем направленный ключ
        let key = await DuoNetCrypto.getDirectionalKey(sessionKeyHex, fromId, toId);

        // 2. Если есть фраза — комбинируем
        if (phrase) {
            const salt = crypto.getRandomValues(new Uint8Array(16));
            const saltHex = Array.from(salt).map(b => b.toString(16).padStart(2, '0')).join('');
            const phraseKeyHex = await DuoNetCrypto.derivePhraseKey(phrase, saltHex);
            key = DuoNetCrypto.xorKeys(key, phraseKeyHex);
            // Сохраняем salt в ciphertext? Для прототипа — пока без salt
        }

        // 3. Шифруем
        const ciphertextHex = await DuoNetCrypto.encryptMessage(plaintext, key);
        return ciphertextHex;
    }

    // Полный цикл расшифровки с направлением и фразой
    async decrypt(ciphertextHex, sessionKeyHex, fromId, toId, phrase = null) {
        // 1. Получаем направленный ключ
        let key = await DuoNetCrypto.getDirectionalKey(sessionKeyHex, fromId, toId);

        // 2. Если есть фраза — комбинируем
        if (phrase) {
            // В прототипе: фраза используется как есть
            const phraseKeyHex = await DuoNetCrypto.derivePhraseKey(phrase, "00000000000000000000000000000000");
            key = DuoNetCrypto.xorKeys(key, phraseKeyHex);
        }

        // 3. Расшифровываем
        return await DuoNetCrypto.decryptMessage(ciphertextHex, key);
    }

    // Управление хранилищем
    setSessionKey(dialogId, sessionKeyHex) {
        this.sessionKeys.set(dialogId, sessionKeyHex);
        // Сохраняем в localStorage
        const stored = JSON.parse(localStorage.getItem('duonet_session_keys') || '{}');
        stored[dialogId] = sessionKeyHex;
        localStorage.setItem('duonet_session_keys', JSON.stringify(stored));
    }

    getSessionKey(dialogId) {
        // Сначала из памяти
        if (this.sessionKeys.has(dialogId)) {
            return this.sessionKeys.get(dialogId);
        }
        // Потом из localStorage
        const stored = JSON.parse(localStorage.getItem('duonet_session_keys') || '{}');
        if (stored[dialogId]) {
            this.sessionKeys.set(dialogId, stored[dialogId]);
            return stored[dialogId];
        }
        return null;
    }

    setPhrase(contactId, phrase) {
        this.phrases.set(contactId, phrase);
        // Не сохраняем фразу в localStorage (безопасность)
    }

    getPhrase(contactId) {
        return this.phrases.get(contactId);
    }

    clearPhrase(contactId) {
        this.phrases.delete(contactId);
    }
}

window.DuoNetCrypto = DuoNetCrypto;
