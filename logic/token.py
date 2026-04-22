import os
import json
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ------------------ TOKEN ------------------
def build_token_payload(
    entry_number: str,
    eid_vector: str,
    booth: int
) -> dict:
    """
    Minimalist payload optimized for space.
    v: voter_id
    e: eid_vector
    b: booth
    """
    return {
        "v": entry_number,
        "e": eid_vector,
        "b": booth
    }

def encrypt_payload_aes(payload: dict, key_hex: str) -> str:
    """
    Returns encrypted string (base64) using AES-256-GCM.
    Format: nonce(12) + tag(16) + ciphertext
    """
    key = bytes.fromhex(key_hex)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    
    plaintext = json.dumps(payload, separators=(",", ":")).encode('utf-8')
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    
    # nonce + ciphertext (which contains the 16-byte tag at the end in cryptography's impl)
    combined = nonce + ciphertext
    return base64.b64encode(combined).decode("utf-8")

def decrypt_payload_aes(ciphertext_b64: str, key_hex: str) -> dict:
    """
    Decrypts the AES-GCM payload.
    """
    try:
        key = bytes.fromhex(key_hex)
        aesgcm = AESGCM(key)
        data = base64.b64decode(ciphertext_b64)
        
        nonce = data[:12]
        ciphertext = data[12:]
        
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return json.loads(plaintext.decode('utf-8'))
    except Exception as e:
        print(f"Decryption error: {e}")
        return None
