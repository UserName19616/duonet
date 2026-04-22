# DuoNet — Decentralized Private Communication Network

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)]()
[![Documentation](https://img.shields.io/badge/docs-WIP-yellow.svg)]()

> **⚠️ DISCLAIMER: This is a DEMONSTRATION PROTOTYPE / Alpha Version**
>
> This project is a **proof of concept** demonstrating that a decentralized, server-blind, legally-grounded communication network is technically possible. The code is functional for educational and demonstration purposes but is **NOT yet production-ready**.
>
> **🚀 Future development depends on the community!** If you have the skills and desire to develop this project further — whether it's cryptography, networking, web/mobile UI, or protocol design — please reach out to the author:
>
> **📧 Alexey Nikolaev: leha.nikolaev@gmail.com**
>
> *Let's build a truly free and decentralized communication network together.*

---

## 📖 Table of Contents

- [What is DuoNet?](#what-is-duonet)
- [Key Features](#key-features)
- [Unique Concepts](#unique-concepts)
- [Technology Stack](#technology-stack)
- [Quick Start (Demo)](#quick-start-demo)
- [Educational Use](#educational-use)
- [Project Status](#project-status)
- [How to Contribute](#how-to-contribute)
- [License](#license)

---

## What is DuoNet?

DuoNet is an experimental **decentralized communication network** that combines:

- **End-to-end encrypted messaging** (E2EE) with post-compromise security
- **Blind server architecture** — servers relay encrypted messages without ever seeing plaintext
- **Community Charter** — a social contract defining the network's values and limits
- **Built-in proxy service** — share your internet connection and earn trust
- **Peer discovery** via mDNS (local network) and Rendezvous servers (global)

Unlike traditional messengers, DuoNet has **no central authority**, **no company behind it**, and **no single point of control**. The technology is declared as **public domain** (Article 1 of the Charter), meaning no one can patent, restrict, or monopolize it.

---

## ✨ Key Features

### Already Implemented (Alpha)

| Feature | Status | Description |
|---------|--------|-------------|
| **Account Registration** | ✅ | Email-based seed phrases, region selection, dual accounts (client+server) |
| **End-to-End Encryption** | ✅ | AES-256-GCM with directional keys, LRP (Lottery Ratchet Protocol) |
| **Key Rotation (V4)** | ✅ | Client-only ECDH (X25519) rotation, server-blind |
| **WebSocket Messaging** | ✅ | Real-time message relay, typing indicators, online status |
| **Invite Protocol** | ✅ | Cryptographically signed invites with spam protection |
| **Web UI** | ✅ | Full-featured web interface for messaging and contact management |
| **Rendezvous Server** | ✅ | Global server discovery by region |
| **Trust System** | ⚠️ | Basic levels (UNKNOWN → QUARANTINE → TRUSTED), voting is stub |
| **Proxy Service** | ✅ | HTTP/HTTPS proxy with traffic limits and client groups |
| **Network Map** | ✅ | Local network discovery via mDNS |
| **Gossip Protocol** | ⚠️ | Basic sync implemented, full P2P pending |
| **Load Balancer** | ⚠️ | Metrics collection and reconnect suggestions, auto-balance pending |
| **TUI Client** | 🚧 | Partially implemented (use Web UI instead) |

### Roadmap (Needs Contributors!)

- **Mobile clients** (iOS/Android via Flutter or React Native)
- **Desktop app** (Electron or native)
- **Validator nodes** — for network consensus and reputation
- **Full P2P mode** — direct client-to-client when possible
- **File sharing** with end-to-end encryption
- **Voice/Video calls** (WebRTC)
- **Plugin system** for extensibility

---

## 🧠 Unique Concepts

### 1. The DuoNet Community Charter

This is **not a legal document** but a **social contract** that participants voluntarily accept. Key articles:

- **Article 1 (Public Domain)** — The technology belongs to all humanity. No patents, no restrictions.
- **Article 4.5 (Server Limit)** — A server operator must not serve more than **450 unique users per day**. This prevents centralization.
- **Article 6.1 (No Moderation)** — The network does not have moderation, bans, or control mechanisms. Technology is a tool, not a judge.

The Charter is cryptographically signed by each account upon registration.

### 2. Blind Server Architecture

The server **never sees plaintext**. All messages (including system messages like key rotation requests) are end-to-end encrypted. The server is a **dumb relay** — it stores and forwards encrypted blobs without any ability to inspect them.

### 3. LRP (Lottery Ratchet Protocol)

Instead of a single session key, DuoNet generates a **pool of 16 keys** from the original session key. Each message randomly selects one key from the pool. This makes traffic analysis significantly harder because packets look different even within the same conversation.

### 4. Client-Only Key Rotation (V4)

Key rotation uses **ECDH (X25519)** and is performed **entirely between clients**. The server is not involved — rotation requests and responses are just encrypted messages like any other. The server cannot even detect that a rotation is happening.

### 5. Proxy Service as Built-in Economy

Users can run a proxy server on their home computer and invite others to use it. Different access tiers (`basic`, `standard`, `privileged`) with daily traffic limits. This creates a decentralized, trust-based economy.

---

## 🛠 Technology Stack

| Component | Technologies |
|-----------|--------------|
| **Backend** | Python 3.10+, FastAPI, asyncio, websockets |
| **Cryptography** | AES-256-GCM, X25519 (ECDH), Ed25519, HKDF, PBKDF2 |
| **Database** | SQLite (WAL mode) |
| **Web Frontend** | HTML5, TailwindCSS, vanilla JavaScript, Web Crypto API |
| **TUI** | Textual (Python) — partial |
| **Network** | aiohttp, websockets, zeroconf (mDNS) |
| **Testing** | pytest, pytest-asyncio, Playwright |

---

## 🚀 Quick Start (Demo)

### Prerequisites
- Python 3.10 or higher
- OpenSSL
- Linux/macOS/WSL (Windows support coming)

### Installation

```bash
# Clone the repository (replace with actual URL)
git clone https://github.com/YOUR_USERNAME/duonet.git
cd duonet

# Run the installer (creates venv, generates SSL certs, sets up databases)
./install.sh

# Start the server (web interface + API + rendezvous)
./run_web.sh

# In another terminal, open the web interface
# https://localhost:8443
⚠️ Important: The first time you run, you'll need to:

Accept the self-signed SSL certificate warning

Register a server account (type: Server) — this creates both server and client accounts

Then you can register additional client accounts (up to 3 per IP)

Access Points
Service	URL
Web UI	https://localhost:8443
Swagger API Docs	https://localhost:8443/docs
Rendezvous Server API	http://localhost:9878/api/health
Proxy Server	http://localhost:9879
🎓 Educational Use
DuoNet is an excellent teaching tool for cryptography and network security courses!

What Students Can Learn
Topic	Implementation in DuoNet
Symmetric encryption	AES-256-GCM in src/client/crypto/aes.py
Asymmetric cryptography	Ed25519 signatures, X25519 key exchange
Key derivation	PBKDF2, HKDF in rotation protocol
Perfect Forward Secrecy	ECDH-based key rotation
Secure protocols	Invite protocol with signatures, LRP
Web Crypto API	Client-side encryption in browser
Rate limiting	Distributed rate limiting strategies
Trust systems	Quarantine, voting, reputation
Classroom Exercises
Basic Encryption Lab: Modify examples/basic_encryption.py to add your own message, then decrypt it.

Man-in-the-Middle Detection: Try to intercept a message and see why verification fails.

Key Rotation Analysis: Monitor WebSocket traffic during key rotation — observe that the server sees only encrypted blobs.

Spam Protection Test: Create multiple invites, reject them, and observe the blocking mechanism.

Proxy Traffic Analysis: Run the proxy server and analyze traffic logs (with permission).

Example Code
See the /examples directory for ready-to-run examples:

python
# examples/basic_encryption.py
from src.client.crypto.aes import generate_session_key, encrypt, decrypt

# Alice and Bob share a session key (out-of-band in real life)
session_key = generate_session_key()

# Alice encrypts a message
plaintext = "Hello, Bob! This is a secret."
ciphertext = encrypt(plaintext, session_key)

# Bob decrypts it
decrypted = decrypt(ciphertext, session_key)
print(f"Decrypted: {decrypted}")  # "Hello, Bob! This is a secret."
📊 Project Status
text
Core Infrastructure      ████████████████████ 95% (API, DB, auth)
Cryptography            ████████████████████ 90% (AES, ECDH, LRP, rotation)
Web UI                  ████████████████████ 85% (messaging works)
WebSocket               ████████████████████ 80% (stable)
Trust System            ████████░░░░░░░░░░░░ 40% (basic levels, voting stub)
Gossip Protocol         ████████░░░░░░░░░░░░ 40% (sync stub)
Mobile Clients          ░░░░░░░░░░░░░░░░░░░░  0% (NEEDS CONTRIBUTORS)
Desktop App             ░░░░░░░░░░░░░░░░░░░░  0% (NEEDS CONTRIBUTORS)
TUI Client              ████░░░░░░░░░░░░░░░░ 20% (partial, use Web UI)
Alpha quality: The system works for demonstration and education but has not been audited for security. Do not use for sensitive communications in production.

🤝 How to Contribute
This project lives only because of community interest. If you want to see DuoNet become a real, production-ready network — your contribution matters.

Ways to Contribute
Skill Area	What You Can Do
Cryptography	Audit existing algorithms, implement post-quantum crypto
Python Backend	Fix bugs, optimize performance, implement missing features (gossip, voting)
Web Frontend	Improve UI/UX, add mobile responsiveness, implement file sharing
Mobile Development	Build iOS/Android clients (Flutter/React Native/Kotlin/Swift)
DevOps	Create Docker images, set up CI/CD, write deployment guides
Documentation	Write tutorials, translate to other languages, create video demos
Testing	Write unit/integration tests, set up automated testing
Contact the Author
📧 Alexey Nikolaev: leha.nikolaev@gmail.com

Feel free to reach out with:

Questions about the architecture

Ideas for new features

Offers to collaborate

Bug reports

Development Setup
bash
# Fork and clone the repository
git clone https://github.com/YOUR_USERNAME/duonet.git
cd duonet

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/ -v

# Run the server in development mode
./run_web.sh
Coding Standards
Python: Follow PEP 8, use type hints

JavaScript: Use modern ES6+, avoid jQuery

Documentation: Docstrings for all public functions

Tests: Write tests for new features

📄 License
DuoNet is released under the GNU Affero General Public License v3.0 (AGPL-3.0).

This license ensures that:

The source code remains open and free

Any modifications must also be released under AGPL-3.0

Network service providers must offer source code to users

Additionally, Article 1 of the DuoNet Charter declares the technology as public domain, meaning no entity can claim exclusive rights or patent the algorithms.

🙏 Acknowledgments
The cryptographic community for Ed25519, X25519, and AES-GCM

The Python ecosystem for FastAPI, aiohttp, and cryptography libraries

All contributors who will help shape the future of DuoNet

📞 Contact & Support
Author Email: leha.nikolaev@gmail.com

GitHub Issues: [Link to be added]

Discussion Forum: [Link to be added]

⭐ If you like this project, star it on GitHub and share it with others!

Together, we can build a truly free, private, and decentralized communication network.
