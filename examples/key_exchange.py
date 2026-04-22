#!/usr/bin/env python3
"""
Key Exchange Example for DuoNet Educational Labs

Demonstrates ECDH (X25519) key exchange between Alice and Bob.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.client.crypto.ecdh import generate_ecdh_keypair, compute_shared_secret, derive_new_key


def main():
    print("=" * 60)
    print("DuoNet ECDH Key Exchange Example")
    print("=" * 60)

    # Alice generates her key pair
    alice_priv, alice_pub = generate_ecdh_keypair()
    print(f"\n👩 Alice:")
    print(f"   Private key: {alice_priv.hex()[:16]}...")
    print(f"   Public key:  {alice_pub.hex()[:16]}...")

    # Bob generates his key pair
    bob_priv, bob_pub = generate_ecdh_keypair()
    print(f"\n👨 Bob:")
    print(f"   Private key: {bob_priv.hex()[:16]}...")
    print(f"   Public key:  {bob_pub.hex()[:16]}...")

    # They exchange public keys (over insecure channel)

    # Alice computes shared secret using her private key and Bob's public key
    alice_secret = compute_shared_secret(alice_priv, bob_pub)

    # Bob computes shared secret using his private key and Alice's public key
    bob_secret = compute_shared_secret(bob_priv, alice_pub)

    print(f"\n🤝 Shared secrets:")
    print(f"   Alice's computed: {alice_secret.hex()[:16]}...")
    print(f"   Bob's computed:   {bob_secret.hex()[:16]}...")

    # They should be identical
    if alice_secret == bob_secret:
        print("\n✅ Shared secrets match! Secure channel established.")
    else:
        print("\n❌ Shared secrets do not match! Something went wrong.")

    # Derive a session key from the shared secret
    dialog_id = "alice@example.com:bob@example.com"
    session_key = derive_new_key(alice_secret, dialog_id)
    print(f"\n🔑 Derived session key: {session_key.hex()[:32]}...")

    print("\n" + "=" * 60)
    print("✅ ECDH key exchange works correctly!")
    print("=" * 60)


if __name__ == "__main__":
    main()
