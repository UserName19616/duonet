# DuoNet Cryptography Documentation

This document describes the cryptographic primitives and protocols used in DuoNet.

## Overview

DuoNet uses a hybrid cryptographic approach:

| Purpose | Algorithm | Implementation |
|---------|-----------|----------------|
| **Symmetric encryption** | AES-256-GCM | `src/client/crypto/aes.py` |
| **Key exchange** | X25519 (ECDH) | `src/client/crypto/ecdh.py` |
| **Digital signatures** | Ed25519 | `src/common/crypto/keys.py` |
| **Key derivation** | PBKDF2, HKDF | `src/client/crypto/phrase.py`, `src/client/crypto/ecdh.py` |
| **Password hashing** | bcrypt | `src/common/crypto/hash.py` |

## Key Lengths

| Key Type | Length |
|----------|--------|
| AES-256 key | 32 bytes |
| X25519 private key | 32 bytes |
| X25519 public key | 32 bytes |
| Ed25519 private key | 32 bytes |
| Ed25519 public key | 32 bytes |
| Ed25519 signature | 64 bytes |
| Shared secret (ECDH) | 32 bytes |

## LRP (Lottery Ratchet Protocol)

Instead of using a single session key, DuoNet generates a **pool of 16 keys** from the original session key:
pool[i] = HKDF(session_key, "lottery_key_{i}_v2", dialog_id)

text

Each message randomly selects one key from the pool. The key index is prepended as a single byte to the ciphertext:
[1 byte key_index][12 bytes nonce][ciphertext + GCM tag]

text

The server sees only the encrypted blob and cannot determine which key was used.

## Directional Keys

To prevent replay attacks, each direction uses a different key:
key_AB = session_key XOR SHA256("A:B")
key_BA = session_key XOR SHA256("B:A")

text

## Key Rotation Protocol (V4)

1. **REQUEST** — Initiator generates ephemeral X25519 key pair, sends public key
2. **ACCEPT** — Responder generates own ephemeral key pair, computes shared secret, derives new key
3. **CONFIRM** — Initiator computes shared secret, derives new key, activates it
4. **COMPLETE** — Responder activates new key

All messages are encrypted as regular messages. The server never sees the rotation.

## Phrase Protection (Double Key)

Users can set an additional secret phrase for individual chats:
final_key = directional_key XOR PBKDF2(phrase, salt)

text

The phrase is never stored on the server — only a hash is kept locally.

## Security Assumptions

- AES-256-GCM is secure (no known practical attacks)
- X25519 is secure (discrete log problem on Curve25519)
- Ed25519 is secure (no known collisions)
- The server is honest-but-curious (follows protocol but may try to observe)
- TLS is used for transport security

## Known Limitations (Alpha)

- No post-quantum cryptography (yet)
- No forward secrecy for message history (only future messages after rotation)
- Trust system voting is a stub
- No hardware security module support

## References

- [RFC 5116](https://tools.ietf.org/html/rfc5116) — AES-GCM
- [RFC 7748](https://tools.ietf.org/html/rfc7748) — Curve25519
- [RFC 8032](https://tools.ietf.org/html/rfc8032) — Ed25519
- [RFC 5869](https://tools.ietf.org/html/rfc5869) — HKDF
- [RFC 2898](https://tools.ietf.org/html/rfc2898) — PBKDF2
