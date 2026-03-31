#!/usr/bin/env python3
"""
Standalone RFID token reader + decryptor.

- Reads token written across MIFARE Classic blocks
- Skips sector trailer blocks
- Stops on NULL padding
- Reassembles encrypted token
- Prints decrypted payload
"""

import sys
import time
import board
import busio

from adafruit_pn532.i2c import PN532_I2C
from adafruit_pn532.adafruit_pn532 import MIFARE_CMD_AUTH_B

# ---------------- CONFIG ----------------

START_BLOCK = 4
MAX_BLOCKS = 40            # safety cap
KEY_DEFAULT = b'\xFF' * 6
# ---------------------------------------


def debug(msg):
    print(f"[DEBUG] {msg}", flush=True)


def is_trailer_block(block_no: int) -> bool:
    """MIFARE Classic sector trailer blocks"""
    return (block_no + 1) % 4 == 0


import json
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization

from hardware_crypto import get_hardware_passphrase

def load_bmd_private_key():
    passphrase = get_hardware_passphrase()
    try:
        with open("private.pem", "rb") as f:
            pem_data = f.read()
    except Exception:
        debug("❌ Failed to load private.pem. Has it been generated?")
        sys.exit(1)
        
    try:
        private_key = serialization.load_pem_private_key(
            pem_data,
            password=passphrase
        )
        return private_key
    except Exception as e:
        debug("❌ Failed to unlock private.pem. Wrong hardware passphrase?")
        sys.exit(1)

def decrypt_rsa(encrypted_b64: str, private_key) -> bytes:
    try:
        ciphertext = base64.b64decode(encrypted_b64)
    except Exception as e:
        debug("❌ Failed to base64-decode the token")
        raise e

    try:
        plaintext = private_key.decrypt(
            ciphertext,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        debug("✅ Successfully decrypted payload")
        return plaintext
    except Exception as e:
        raise ValueError(f"Failed to decrypt with the hardware private key: {e}")
    
# Set to True when testing without actual RFID hardware
MOCK_RFID = True

def main():
    debug("Starting RFID read + decrypt tool")

    if MOCK_RFID:
        debug("Running in MOCK_RFID mode")
        debug("Waiting for mock_rfid.txt to be updated...")
        import os
        
        start = time.time()
        while not os.path.exists("mock_rfid.txt") and time.time() - start < 20:
            time.sleep(0.5)
            
        if not os.path.exists("mock_rfid.txt"):
            debug("❌ mock_rfid.txt not found (timeout)")
            sys.exit(1)
            
        with open("mock_rfid.txt", "r") as f:
            encrypted_token = f.read().strip()
            
        if not encrypted_token:
            debug("❌ mock_rfid.txt is empty")
            sys.exit(1)
            
        debug("Encrypted token read from file:")
        debug(encrypted_token)
    else:
        # -----------------------------
        # Init PN532
        # -----------------------------
        debug("Initializing PN532 (I2C)")
        i2c = busio.I2C(board.SCL, board.SDA)
        pn532 = PN532_I2C(i2c, debug=False)
        pn532.SAM_configuration()

        # -----------------------------
        # Wait for card
        # -----------------------------
        debug("Place RFID card on reader")

        uid = None
        start = time.time()
        while uid is None and time.time() - start < 20:
            uid = pn532.read_passive_target(timeout=0.5)

        if uid is None:
            debug("❌ No card detected (timeout)")
            sys.exit(1)

        debug(f"Card detected, UID = {list(uid)}")

        # -----------------------------
        # Read blocks
        # -----------------------------
        block_no = START_BLOCK
        raw_bytes = bytearray()

        debug("Beginning block read")

        for i in range(MAX_BLOCKS):
            # Skip trailer blocks
            while is_trailer_block(block_no):
                debug(f"Skipping trailer block {block_no}")
                block_no += 1

            debug(f"Reading block {block_no}")

            auth = pn532.mifare_classic_authenticate_block(
                uid,
                block_no,
                MIFARE_CMD_AUTH_B,
                KEY_DEFAULT
            )

            if not auth:
                debug(f"❌ Authentication failed at block {block_no}")
                break

            data = pn532.mifare_classic_read_block(block_no)

            if data is None:
                debug(f"❌ Read failed at block {block_no}")
                break

            debug(f"Block {block_no} raw data: {data}")

            # Stop on NULL padding (end of token)
            if b'\x00' in data:
                raw_bytes.extend(data.split(b'\x00')[0])
                debug("NULL terminator encountered — end of token")
                break

            raw_bytes.extend(data)
            block_no += 1

        if not raw_bytes:
            debug("❌ No data read from card")
            sys.exit(1)

        # -----------------------------
        # Reassemble encrypted token
        # -----------------------------
        try:
            encrypted_token = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            debug("❌ Failed to decode encrypted token as UTF-8")
            sys.exit(1)

        debug("Encrypted token reconstructed:")
        debug(encrypted_token)
        debug(f"Encrypted token length = {len(encrypted_token)} chars")

    # -----------------------------
    # Decrypt
    # -----------------------------
    debug("Loading hardware-bound private key")
    private_key = load_bmd_private_key()

    try:
        decrypted = decrypt_rsa(encrypted_token, private_key)
    except Exception as e:
        debug("❌ RSA decryption failed")
        debug(str(e))
        sys.exit(1)

    # -----------------------------
    # Output
    # -----------------------------
    debug("✅ Decryption successful")
    print("\n===== DECRYPTED TOKEN PAYLOAD =====\n")
    print(decrypted.decode("utf-8"))
    print("\n===================================\n")

    debug("Remove card")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user")
        sys.exit(130)
