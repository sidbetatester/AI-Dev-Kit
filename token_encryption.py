"""
token_encryption.py

Secure token storage with encryption using machine-specific keys.
"""

import os
import base64
import hashlib
from pathlib import Path
from typing import Optional

try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


class TokenEncryption:
    """
    Encrypts and decrypts tokens using machine-specific keys.
    
    Uses Fernet (symmetric encryption) with a key derived from machine identifier.
    """
    
    def __init__(self):
        """Initialize token encryption with machine-specific key."""
        self._key = self._get_or_create_key()
        if CRYPTO_AVAILABLE:
            self._cipher = Fernet(self._key)
        else:
            self._cipher = None
    
    def _get_machine_id(self) -> str:
        """
        Get a machine-specific identifier.
        
        Returns:
            A string unique to this machine
        """
        # Use hostname + username as machine ID
        import socket
        import getpass
        
        hostname = socket.gethostname()
        username = getpass.getuser()
        machine_id = f"{hostname}_{username}"
        return machine_id
    
    def _derive_key(self, seed: str) -> bytes:
        """
        Derive a Fernet-compatible key from a seed string.
        
        Args:
            seed: Seed string for key derivation
        
        Returns:
            32-byte key suitable for Fernet
        """
        # Use SHA256 to create a 32-byte hash
        hash_obj = hashlib.sha256(seed.encode('utf-8'))
        key_bytes = hash_obj.digest()
        # Base64 encode to make it Fernet-compatible
        return base64.urlsafe_b64encode(key_bytes)
    
    def _get_or_create_key(self) -> bytes:
        """
        Get or create encryption key based on machine ID.
        
        Returns:
            Encryption key
        """
        machine_id = self._get_machine_id()
        return self._derive_key(machine_id)
    
    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string.
        
        Args:
            plaintext: String to encrypt
        
        Returns:
            Encrypted string (base64 encoded)
        """
        if not CRYPTO_AVAILABLE:
            # Fallback: weak obfuscation (NOT secure, just hides from casual viewing)
            import base64
            return base64.b64encode(plaintext.encode('utf-8')).decode('utf-8')
        
        if not plaintext:
            return ""
        
        encrypted_bytes = self._cipher.encrypt(plaintext.encode('utf-8'))
        return encrypted_bytes.decode('utf-8')
    
    def decrypt(self, encrypted: str) -> str:
        """
        Decrypt an encrypted string.
        
        Args:
            encrypted: Encrypted string (base64 encoded)
        
        Returns:
            Decrypted plaintext string
        """
        if not CRYPTO_AVAILABLE:
            # Fallback: decode weak obfuscation
            import base64
            try:
                return base64.b64decode(encrypted.encode('utf-8')).decode('utf-8')
            except Exception:
                return ""
        
        if not encrypted:
            return ""
        
        try:
            decrypted_bytes = self._cipher.decrypt(encrypted.encode('utf-8'))
            return decrypted_bytes.decode('utf-8')
        except Exception:
            # Decryption failed (corrupted or wrong key)
            return ""
    
    def is_secure(self) -> bool:
        """
        Check if secure encryption is available.
        
        Returns:
            True if cryptography library is available, False if using fallback
        """
        return CRYPTO_AVAILABLE


if __name__ == "__main__":
    # Example usage
    enc = TokenEncryption()
    
    print(f"Secure encryption: {enc.is_secure()}")
    
    # Test encryption/decryption
    test_token = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
    encrypted = enc.encrypt(test_token)
    decrypted = enc.decrypt(encrypted)
    
    print(f"Original:  {test_token}")
    print(f"Encrypted: {encrypted}")
    print(f"Decrypted: {decrypted}")
    print(f"Match: {test_token == decrypted}")
