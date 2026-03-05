import uuid
import json
import base64
from datetime import datetime
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization

# ------------------ BOOTH ------------------
def assign_booth(entry_number: str, eid_vector: str, num_booths: int) -> int:
    return abs(hash(entry_number + eid_vector)) % num_booths + 1

# ------------------ TOKEN ------------------
def build_token_payload(
    entry_number: str,
    eid_vector: str,
    booth: int
) -> dict:
    """
    Plain payload BEFORE encryption.
    """
    return {
        "token_id": str(uuid.uuid4()),
        "voter_id": entry_number,
        "eid_vector": eid_vector,
        "booth": booth,
        "issued_at": datetime.now().isoformat()
    }

def encrypt_payload(payload: dict, public_key_pem: str) -> str:
    """
    Returns encrypted string (base64-safe) using RSA.
    """
    public_key = serialization.load_pem_public_key(
        public_key_pem.encode('utf-8')
    )

    plaintext = json.dumps(payload, separators=(",", ":")).encode('utf-8')
    
    ciphertext = public_key.encrypt(
        plaintext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )

    return base64.b64encode(ciphertext).decode("utf-8")
