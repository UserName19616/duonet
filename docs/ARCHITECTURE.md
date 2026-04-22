# DuoNet Architecture Overview

## High-Level Diagram
┌─────────────────────────────────────────────────────────────────┐
│ INTERNET │
└─────────────────────────────────────────────────────────────────┘
│ │ │
▼ ▼ ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ Rendezvous │ │ Relay Server │ │ Proxy Server │
│ Server │ │ (NAT) │ │ (HTTP/HTTPS) │
│ (Discovery) │ │ │ │ │
└─────────────────┘ └─────────────────┘ └─────────────────┘
│ │ │
└────────────────────┼────────────────────┘
│
┌─────────────────┐
│ WebSocket │
│ Connection │
└─────────────────┘
│
┌───────────────┼───────────────┐
▼ ▼ ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│ Client A │ │ Client B │ │ Client C │
│ (Alice) │ │ (Bob) │ │ (Proxy) │
└──────────┘ └──────────┘ └──────────┘

text

## Core Components

### 1. Client (`src/client/`)
- `api_client.py` — HTTP client for backend API
- `crypto/` — All cryptographic primitives (AES, ECDH, LRP, directional keys)
- `messaging/` — Message routing, rotation manager, invite protocol
- `storage/` — Local SQLite storage for messages and contacts
- `screens/` — TUI screens (partial)

### 2. Server (`src/server/`)
- `api/` — FastAPI endpoints (auth, messages, contacts, proxy, charter)
- `network/` — Rendezvous, gossip, network map, trust system, load balancer
- `proxy/` — HTTP proxy server, client management, invite generation
- `storage/` — Server database (duonet_server.db)

### 3. Web (`src/web/`)
- `templates/` — Jinja2 HTML templates
- `static/` — CSS, JavaScript (crypto, WebSocket, UI)
- `auth.py`, `contacts.py`, `chat/`, `monitor.py` — Web routes

### 4. Common (`src/common/`)
- `crypto/` — Shared crypto (hash, keys, padding)
- `identity/` — Account management, public ID generation, recovery
- `storage/` — SQLite key-value storage
- `charter/` — Charter loader and signer
- `utils/` — GeoIP utilities

## Message Flow
Alice (Web) Server (Relay) Bob (Web)
│ │ │
│ 1. Encrypt message with │ │
│ directional key + LRP │ │
│ │ │
│ 2. WebSocket.send({ │ │
│ type: "message", │ │
│ encrypted: "...", │ │
│ session_key: "..." │ │
│ }) │ │
│───────────────────────────────>│ │
│ │ │
│ │ 3. Store encrypted blob │
│ │ in messages table │
│ │ │
│ │ 4. Forward to Bob │
│ │─────────────────────────────>│
│ │ │
│ │ │ 5. Decrypt with
│ │ │ directional key
│ │ │
│ 6. Delivery confirmation │ │
│<───────────────────────────────│ │

text

## Key Rotation Protocol (V4)
Alice Bob
│ │
│ 1. Generate ephemeral keys │
│ (eph_priv_a, eph_pub_a) │
│ │
│ 2. Send rotation_request │
│ {__type:"system", │
│ subtype:"rotation_request",│
│ eph_public_key: eph_pub_a} │
│────────────────────────────────>│
│ │
│ │ 3. Generate ephemeral keys
│ │ (eph_priv_b, eph_pub_b)
│ │
│ │ 4. Compute shared_secret
│ │ = ECDH(eph_priv_b, eph_pub_a)
│ │
│ │ 5. Derive new_session_key
│ │
│ 6. Send rotation_accept │
│ {__type:"system", │
│ subtype:"rotation_accept", │
│ eph_public_key: eph_pub_b} │
│<────────────────────────────────│
│ │
│ 7. Compute shared_secret │
│ = ECDH(eph_priv_a, eph_pub_b)
│ │
│ 8. Derive new_session_key │
│ (must match Bob's) │
│ │
│ 9. Send rotation_confirm │
│────────────────────────────────>│
│ │
│ │ 10. Activate new key
│ │
│ 11. Send rotation_complete │
│<────────────────────────────────│
│ │
│ 12. Activate new key │

text

## Database Schema

### Client Database (`duonet.db`)

| Table | Purpose |
|-------|---------|
| `storage` | Key-value storage (contacts, settings) |
| `dialogs` | user_id, contact_id, session_key |
| `messages` | All messages (encrypted) |
| `rotation_state` | Pending rotation requests |

### Server Database (`duonet_server.db`)

| Table | Purpose |
|-------|---------|
| `accounts` | User accounts (seed_hash, public keys) |
| `servers` | Known relay servers |
| `clients` | Registered clients |
| `invites` | Pending/accepted invites |
| `trust_levels` | Trust scores for servers |
| `peers` | Connected servers for gossip |

## Security Considerations

1. **No server-side decryption** — Server only sees encrypted blobs
2. **Directional keys** — Separate keys for A→B and B→A
3. **LRP (Lottery Ratchet)** — Random key selection from 16-key pool
4. **Post-compromise security** — Regular key rotation (every 100 messages or on demand)
5. **Phrase protection** — Second factor for individual chats
6. **Invite signatures** — Cryptographically signed invites prevent spoofing
