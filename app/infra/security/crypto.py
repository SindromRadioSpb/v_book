"""Cryptographic utilities for HDLE Premium.

Provides AES-256-GCM authenticated encryption for credential storage.

Security properties:
- AES-256-GCM: Authenticated encryption (confidentiality + integrity)
- Random nonce per encryption (never reused)
- Authentication tag prevents tampering
- Constant-time comparison for tag verification
"""

import os
import secrets
from typing import Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from .policy import AES_KEY_SIZE, AES_NONCE_SIZE
from .errors import CredentialStoreError


def generate_key() -> bytes:
    """
    Generate a secure random AES-256 key.

    Returns:
        32-byte (256-bit) random key suitable for AES-256-GCM

    Usage:
        master_key = generate_key()
        # Store master_key in OS keyring
    """
    return secrets.token_bytes(AES_KEY_SIZE)


def encrypt(plaintext: bytes, key: bytes) -> bytes:
    """
    Encrypt plaintext using AES-256-GCM.

    Format of ciphertext:
        nonce (12 bytes) || ciphertext || tag (16 bytes)

    Args:
        plaintext: Data to encrypt
        key: 32-byte AES-256 key

    Returns:
        Encrypted data with nonce and tag prepended

    Raises:
        CredentialStoreError: If encryption fails
    """
    if len(key) != AES_KEY_SIZE:
        raise CredentialStoreError(
            f"Invalid key size: {len(key)} (expected {AES_KEY_SIZE})",
            operation="encrypt",
        )

    try:
        # Generate random nonce (MUST be unique per encryption)
        nonce = os.urandom(AES_NONCE_SIZE)

        # Encrypt with AEAD
        aesgcm = AESGCM(key)
        ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext, associated_data=None)

        # Return: nonce || ciphertext || tag
        return nonce + ciphertext_with_tag

    except Exception as e:
        raise CredentialStoreError(
            f"Encryption failed: {e}",
            operation="encrypt",
        )


def decrypt(ciphertext: bytes, key: bytes) -> bytes:
    """
    Decrypt ciphertext using AES-256-GCM.

    Expected format:
        nonce (12 bytes) || ciphertext || tag (16 bytes)

    Args:
        ciphertext: Encrypted data (from encrypt())
        key: 32-byte AES-256 key

    Returns:
        Decrypted plaintext

    Raises:
        CredentialStoreError: If decryption fails or authentication tag is invalid
    """
    if len(key) != AES_KEY_SIZE:
        raise CredentialStoreError(
            f"Invalid key size: {len(key)} (expected {AES_KEY_SIZE})",
            operation="decrypt",
        )

    if len(ciphertext) < AES_NONCE_SIZE + 16:  # nonce + min tag size
        raise CredentialStoreError(
            "Ciphertext too short (corrupted or invalid)",
            operation="decrypt",
        )

    try:
        # Extract nonce and ciphertext+tag
        nonce = ciphertext[:AES_NONCE_SIZE]
        ciphertext_with_tag = ciphertext[AES_NONCE_SIZE:]

        # Decrypt and verify tag
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext_with_tag, associated_data=None)

        return plaintext

    except InvalidTag:
        # Authentication failed - data was tampered with or corrupted
        raise CredentialStoreError(
            "Decryption failed: authentication tag invalid (data corrupted or tampered)",
            operation="decrypt",
        )
    except Exception as e:
        raise CredentialStoreError(
            f"Decryption failed: {e}",
            operation="decrypt",
        )


def derive_key_from_password(password: str, salt: bytes) -> bytes:
    """
    Derive encryption key from password using PBKDF2.

    WARNING: Password-based encryption is weaker than random keys.
    Only use if OS keyring is unavailable.

    Args:
        password: User password
        salt: Random salt (at least 16 bytes)

    Returns:
        32-byte derived key

    Note:
        Currently not used - master key stored in OS keyring.
        Kept for future use if keyring unavailable.
    """
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=AES_KEY_SIZE,
        salt=salt,
        iterations=600_000,  # OWASP recommendation (2023)
    )
    return kdf.derive(password.encode('utf-8'))
