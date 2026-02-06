"""Secure credential storage for HDLE Premium.

Architecture:
- Master key stored in OS keyring (Windows Credential Manager, macOS Keychain, Linux Secret Service)
- Credential values encrypted at rest using AES-256-GCM
- Encrypted credentials stored in SQLite database

Security:
- Master key never touches disk (OS keyring handles secure storage)
- All credential values encrypted with AES-256-GCM
- Authentication tag prevents tampering
- Constant-time comparison for integrity
"""

import base64
import keyring
from typing import Optional, Dict

from .crypto import generate_key, encrypt, decrypt
from .policy import CREDENTIAL_KEY_MAX_LENGTH, CREDENTIAL_VALUE_MAX_LENGTH
from .errors import CredentialStoreError, ValidationError


# Keyring service name for this application
KEYRING_SERVICE = "HDLE_Premium"
KEYRING_MASTER_KEY = "master_encryption_key"


class CredentialStore:
    """
    Secure credential storage with OS keyring + encrypted database.

    Usage:
        store = CredentialStore()
        store.set_credential("openai_api_key", "sk-...")
        api_key = store.get_credential("openai_api_key")
        store.delete_credential("openai_api_key")
    """

    def __init__(self):
        """Initialize credential store and ensure master key exists."""
        self._master_key: Optional[bytes] = None
        self._ensure_master_key()

    def _ensure_master_key(self) -> None:
        """
        Ensure master encryption key exists in OS keyring.

        If no key exists, generates and stores a new one.
        """
        try:
            # Try to retrieve existing master key
            key_b64 = keyring.get_password(KEYRING_SERVICE, KEYRING_MASTER_KEY)

            if key_b64:
                # Decode from base64
                self._master_key = base64.b64decode(key_b64)
            else:
                # Generate new master key
                self._master_key = generate_key()

                # Store in OS keyring (base64 encoded for text storage)
                key_b64 = base64.b64encode(self._master_key).decode('ascii')
                keyring.set_password(KEYRING_SERVICE, KEYRING_MASTER_KEY, key_b64)

        except Exception as e:
            raise CredentialStoreError(
                f"Failed to initialize master key: {e}",
                operation="init",
            )

    def _get_master_key(self) -> bytes:
        """
        Get master encryption key.

        Returns:
            32-byte AES-256 key

        Raises:
            CredentialStoreError: If master key unavailable
        """
        if self._master_key is None:
            raise CredentialStoreError(
                "Master key not initialized",
                operation="get_master_key",
            )
        return self._master_key

    def encrypt_value(self, plaintext: str) -> str:
        """
        Encrypt credential value.

        Args:
            plaintext: Credential value to encrypt

        Returns:
            Base64-encoded encrypted value

        Raises:
            ValidationError: If value exceeds size limit
            CredentialStoreError: If encryption fails
        """
        # Validate size
        if len(plaintext) > CREDENTIAL_VALUE_MAX_LENGTH:
            raise ValidationError(
                f"Credential value too large: {len(plaintext)} chars "
                f"(max {CREDENTIAL_VALUE_MAX_LENGTH})",
                field="credential_value",
                value=plaintext[:100] + "...",
            )

        # Encrypt
        master_key = self._get_master_key()
        ciphertext = encrypt(plaintext.encode('utf-8'), master_key)

        # Return as base64 for text storage
        return base64.b64encode(ciphertext).decode('ascii')

    def decrypt_value(self, ciphertext_b64: str) -> str:
        """
        Decrypt credential value.

        Args:
            ciphertext_b64: Base64-encoded encrypted value

        Returns:
            Decrypted plaintext

        Raises:
            CredentialStoreError: If decryption fails or data corrupted
        """
        try:
            # Decode from base64
            ciphertext = base64.b64decode(ciphertext_b64)

            # Decrypt
            master_key = self._get_master_key()
            plaintext_bytes = decrypt(ciphertext, master_key)

            return plaintext_bytes.decode('utf-8')

        except Exception as e:
            raise CredentialStoreError(
                f"Failed to decrypt credential: {e}",
                operation="decrypt_value",
            )

    def set_credential(
        self,
        key: str,
        value: str,
        storage: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Store encrypted credential.

        Args:
            key: Credential key (e.g., "openai_api_key")
            value: Credential value (plaintext, will be encrypted)
            storage: Optional dict for in-memory storage (default: use DB)

        Raises:
            ValidationError: If key/value invalid
            CredentialStoreError: If storage fails

        Note:
            In production, credentials stored in database table:
            CREATE TABLE credentials (
                key TEXT PRIMARY KEY,
                encrypted_value TEXT NOT NULL
            )
        """
        # Validate key
        if not key or len(key) > CREDENTIAL_KEY_MAX_LENGTH:
            raise ValidationError(
                f"Invalid credential key (max {CREDENTIAL_KEY_MAX_LENGTH} chars)",
                field="credential_key",
                value=key,
            )

        # Encrypt value
        encrypted_value = self.encrypt_value(value)

        # Store (in-memory or database)
        if storage is not None:
            # In-memory storage (for testing or config)
            storage[key] = encrypted_value
        else:
            # TODO: Store in database
            # db.execute("INSERT OR REPLACE INTO credentials (key, encrypted_value) VALUES (?, ?)",
            #            (key, encrypted_value))
            raise NotImplementedError(
                "Database credential storage not yet implemented. "
                "Pass 'storage' dict for in-memory mode."
            )

    def get_credential(
        self,
        key: str,
        storage: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """
        Retrieve and decrypt credential.

        Args:
            key: Credential key
            storage: Optional dict for in-memory storage (default: use DB)

        Returns:
            Decrypted credential value, or None if not found

        Raises:
            CredentialStoreError: If decryption fails
        """
        # Retrieve encrypted value
        if storage is not None:
            # In-memory storage
            encrypted_value = storage.get(key)
        else:
            # TODO: Retrieve from database
            # row = db.execute("SELECT encrypted_value FROM credentials WHERE key = ?", (key,)).fetchone()
            # encrypted_value = row[0] if row else None
            raise NotImplementedError(
                "Database credential storage not yet implemented. "
                "Pass 'storage' dict for in-memory mode."
            )

        if encrypted_value is None:
            return None

        # Decrypt
        return self.decrypt_value(encrypted_value)

    def delete_credential(
        self,
        key: str,
        storage: Optional[Dict[str, str]] = None,
    ) -> bool:
        """
        Delete credential.

        Args:
            key: Credential key
            storage: Optional dict for in-memory storage (default: use DB)

        Returns:
            True if credential was deleted, False if not found
        """
        if storage is not None:
            # In-memory storage
            if key in storage:
                del storage[key]
                return True
            return False
        else:
            # TODO: Delete from database
            # result = db.execute("DELETE FROM credentials WHERE key = ?", (key,))
            # return result.rowcount > 0
            raise NotImplementedError(
                "Database credential storage not yet implemented. "
                "Pass 'storage' dict for in-memory mode."
            )

    @staticmethod
    def reset_master_key() -> None:
        """
        Delete master key from OS keyring.

        WARNING: This will make all stored credentials unrecoverable!
        Only use for testing or emergency key rotation.
        """
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_MASTER_KEY)
        except keyring.errors.PasswordDeleteError:
            # Key doesn't exist, ignore
            pass
