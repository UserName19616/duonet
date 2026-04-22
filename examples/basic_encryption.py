#!/usr/bin/env python3
"""
Basic Encryption Example for DuoNet Educational Labs

Demonstrates AES-256-GCM encryption and decryption.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.client.crypto.aes import generate_session_key, encrypt, decrypt


def main():
    print("=" * 60)
    print("DuoNet Basic Encryption Example")
    print("=" * 60)

    # Generate a random session key (32 bytes = 256 bits)
    session_key = generate_session_key()
    print(f"\n🔑 Session key (hex): {session_key.hex()[:32]}...")

    # Original message
    plaintext = "Hello, Bob! This is a secret message."
    print(f"\n📝 Original message: {plaintext}")

    # Encrypt
    ciphertext = encrypt(plaintext, session_key)
    print(f"\n🔒 Encrypted (hex): {ciphertext.hex()[:64]}...")

    # Decrypt with correct key
    decrypted = decrypt(ciphertext, session_key)
    print(f"\n🔓 Decrypted: {decrypted}")

    # Try with wrong key
    wrong_key = generate_session_key()
    decrypted_wrong = decrypt(ciphertext, wrong_key)
    print(f"\n❌ Decryption with wrong key: {decrypted_wrong}")

    print("\n" + "=" * 60)
    print("✅ Encryption/decryption works correctly!")
    print("=" * 60)


if __name__ == "__main__":
    main()
