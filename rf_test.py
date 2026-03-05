#!/usr/bin/env python3
"""
Standalone RFID token write tester.

- Generates a fake encrypted token (same as app.py)
- Writes it using RFIDTokenWriter
- Prints LOTS of debug output
- No Tkinter
- No camera
- No database
"""

import sys
import time
from logic.token import build_token_payload, encrypt_payload
from hardware.rfid_writer import RFIDTokenWriter


def debug(msg):
    print(f"[DEBUG] {msg}", flush=True)


def main():
    debug("Starting RFID token write tester")

    # -----------------------------
    # Fake voter data (hardcoded)
    # -----------------------------
    entry_number = "TEST2024EE0001"
    eid_vector = "FAKE_ELECTION_VECTOR"
    booth = 7

    debug(f"Entry Number : {entry_number}")
    debug(f"EID Vector   : {eid_vector}")
    debug(f"Booth Number : {booth}")

    # -----------------------------
    # Build token payload (same as app.py)
    # -----------------------------
    payload = build_token_payload(
        entry_number=entry_number,
        eid_vector=eid_vector,
        booth=booth
    )

    debug("Token payload created:")
    for k, v in payload.items():
        debug(f"  {k}: {v}")

    # -----------------------------
    # Encrypt token
    # -----------------------------
    encrypted_token = encrypt_payload(payload)

    debug("Encrypted token generated")
    debug(f"Encrypted token length (chars): {len(encrypted_token)}")

    blocks = [encrypted_token[i:i + 16]
              for i in range(0, len(encrypted_token), 16)]

    debug(f"Total RFID blocks required: {len(blocks)}")

    for i, blk in enumerate(blocks):
        debug(f"Block {i+1}: '{blk}'")

    # -----------------------------
    # Initialize RFID writer
    # -----------------------------
    debug("Initializing RFIDTokenWriter (PN532)")
    writer = RFIDTokenWriter(start_block=4)

    # -----------------------------
    # Status callback
    # -----------------------------
    def status_cb(msg):
        print(f"[RFID] {msg}", flush=True)

    # -----------------------------
    # Write token
    # -----------------------------
    debug("Beginning RFID write process")
    start = time.time()

    success = writer.write_token(
        encrypted_token,
        status_cb=status_cb
    )

    elapsed = time.time() - start

    debug(f"RFID write completed in {elapsed:.2f} seconds")

    if success:
        debug("✅ RFID WRITE SUCCESSFUL")
        debug("Remove card and test with another card if needed")
        sys.exit(0)
    else:
        debug("❌ RFID WRITE FAILED")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user")
        sys.exit(130)

