# Using DuoNet for Educational Purposes

DuoNet is an excellent platform for teaching cryptography and network security. This guide explains how to use it in classroom settings.

## Target Audience

- University students (Computer Science, Cybersecurity)
- Self-learners interested in applied cryptography
- Workshop participants

## Prerequisites for Students

- Basic Python knowledge
- Understanding of symmetric/asymmetric encryption concepts
- Familiarity with HTTP/WebSocket (helpful but not required)

## Recommended Lab Structure

### Lab 1: Symmetric Encryption (AES-256-GCM)

**Objective**: Understand how AES-GCM works and implement basic encryption/decryption.

**Tasks**:
1. Run `examples/basic_encryption.py`
2. Modify the plaintext and observe ciphertext changes
3. Try to decrypt with a wrong key — see that it fails

**Key Concepts**:
- Nonce (IV) randomness
- Authentication tag
- Key length (32 bytes = 256 bits)

### Lab 2: Asymmetric Cryptography (Ed25519)

**Objective**: Learn about digital signatures and key pairs.

**Tasks**:
1. Generate a key pair using `src/common/crypto/keys.py`
2. Sign a message and verify the signature
3. Modify the message by 1 byte — see verification fail

**Key Concepts**:
- Public/private key pairs
- Deterministic signatures
- 64-byte signature size

### Lab 3: Key Exchange (X25519)

**Objective**: Understand Diffie-Hellman key exchange.

**Tasks**:
1. Run `examples/key_exchange.py` (to be created)
2. Observe how Alice and Bob derive the same shared secret
3. Try to compute the secret from public keys only — impossible!

**Key Concepts**:
- Elliptic curve cryptography
- Shared secret derivation
- Perfect Forward Secrecy

### Lab 4: End-to-End Encryption in Practice

**Objective**: See how E2EE works in a real messaging system.

**Tasks**:
1. Start two browser windows (Alice and Bob)
2. Send messages between them
3. Inspect WebSocket traffic in browser DevTools
4. Observe that all messages are encrypted (can't read plaintext)

**Key Concepts**:
- Server as blind relay
- Directional keys
- LRP (Lottery Ratchet)

### Lab 5: Key Rotation Attack Analysis

**Objective**: Understand post-compromise security.

**Tasks**:
1. Initiate key rotation between Alice and Bob
2. Capture network traffic during rotation
3. Analyze that the server sees only encrypted rotation messages
4. Try to compromise the old key — see that new messages are still secure

**Key Concepts**:
- ECDH key exchange
- Post-compromise security
- Forward secrecy

### Lab 6: Spam Protection System

**Objective**: Learn about rate limiting and trust systems.

**Tasks**:
1. Send multiple invites from the same user
2. Reject them repeatedly
3. Observe when the user gets blocked
4. Check the spam_protection table in the database

**Key Concepts**:
- Rate limiting strategies
- Exponential backoff
- Block levels (1, 2, 3)

## Classroom Discussion Questions

1. **Why does the server limit itself to 450 users/day?** (Answer: Prevents centralization)
2. **What happens if the original development team abandons the project?** (Answer: Article 1.5 — anyone can continue)
3. **Can the server operator read your messages?** (Answer: No — all messages are end-to-end encrypted)
4. **Why does DuoNet use LRP instead of Double Ratchet (Signal)?** (Answer: Simplicity for demonstration, but can be upgraded)
5. **What is the role of the Rendezvous server?** (Answer: Discovery only — doesn't handle messages)

## Advanced Projects for Students

1. **Implement a missing feature** (e.g., file sharing)
2. **Write a security audit report** for one of the crypto modules
3. **Create a mobile client** using the existing API
4. **Improve the gossip protocol** for better P2P synchronization
5. **Add post-quantum cryptography** (Kyber, Dilithium) as an option

## Getting Help

- **Author email**: leha.nikolaev@gmail.com
- **GitHub Issues**: [Link to be added]
- **Discussion Forum**: [Link to be added]

## License for Educational Use

The code is AGPL-3.0 licensed, which means:
- You can freely use it for teaching
- You must share modifications if you distribute them
- You cannot make a proprietary version

For classroom use, this is ideal — students can see, modify, and learn from the source code.
