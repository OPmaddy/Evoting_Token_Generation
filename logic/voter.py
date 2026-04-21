"""
Hybrid voter status management: local SQLite + central server API.

The LOCAL SQLite database stores device-specific data:
  - Image paths from face verification
  - Timestamps of token generation
  - Full audit trail for this device

The CENTRAL SERVER (MongoDB via REST API) handles synchronisation:
  - Prevents duplicate token generation across multiple devices
  - Tracks which device is currently processing a voter
  - Provides the authoritative "has this voter been issued a token?" answer

Every API call is logged to logs/requests.log immediately (flush + fsync).
Critical failures (cancel / confirm) are persisted to unsynced_requests.json
for replay on the next device startup.
"""

import sqlite3
import os
import requests

from client_config import (
    SERVER_URL,
    DEVICE_ID,
    CLIENT_CERT,
    CLIENT_KEY,
    CA_CERT,
    DISABLE_TLS,
)
from logic.journal import RequestJournal

DB_PATH = "voters.db"
ELECTORAL_ROLL_PATH = "./Electoral_Roll.csv"

SCHEMA = """
CREATE TABLE IF NOT EXISTS voters (
    Entry_Number TEXT PRIMARY KEY,
    Name TEXT,
    EID_Vector TEXT,
    Token_Timestamp TEXT,
    TokenID TEXT,
    Image1Path TEXT,
    Image2Path TEXT,
    Booth_Number TEXT
);
"""


class VoterDB:
    """
    Hybrid voter database: local SQLite for device-specific audit data,
    central server API for cross-device synchronisation.

    All outgoing API calls are:
      1. Logged immediately to logs/requests.log (flush + fsync)
      2. For cancel/confirm failures: persisted to unsynced_requests.json
         so they are replayed automatically on the next startup.
    """

    def __init__(self, db_path=DB_PATH):
        # ── Local SQLite ──────────────────────────────────────────────
        self.db_path = db_path
        self._ensure_db()

        # ── Remote Server ─────────────────────────────────────────────
        self.base_url  = SERVER_URL.rstrip("/")
        self.device_id = DEVICE_ID
        self.session   = requests.Session()
        self._configure_tls()

        # ── Request Journal ───────────────────────────────────────────
        self.journal = RequestJournal()

    # ══════════════════════════════════════════════════════════════════
    #  LOCAL SQLite
    # ══════════════════════════════════════════════════════════════════

    def _ensure_db(self):
        first_time = not os.path.exists(self.db_path)
        conn = sqlite3.connect(self.db_path)
        cur  = conn.cursor()
        cur.execute(SCHEMA)

        # Migration: ensure Booth_Number column exists in older DBs
        try:
            cur.execute("ALTER TABLE voters ADD COLUMN Booth_Number TEXT")
        except sqlite3.OperationalError:
            pass

        conn.commit()

        if first_time:
            self._import_electoral_roll(conn)

        conn.close()

    def _import_electoral_roll(self, conn):
        import pandas as pd
        df = pd.read_csv(ELECTORAL_ROLL_PATH)

        cur = conn.cursor()
        for _, r in df.iterrows():
            cur.execute(
                """
                INSERT OR IGNORE INTO voters
                VALUES (?, ?, ?, NULL, NULL, NULL, NULL, NULL)
                """,
                (
                    str(r["Entry_Number"]).strip(),
                    r["Name"],
                    r["Vector"]
                )
            )
        conn.commit()

    def _get_voter_local(self, entry_number: str):
        """Fetch voter from the local SQLite database."""
        conn = sqlite3.connect(self.db_path)
        cur  = conn.cursor()

        cur.execute(
            "SELECT * FROM voters WHERE lower(Entry_Number)=?",
            (entry_number.lower(),)
        )

        row = cur.fetchone()
        conn.close()

        if not row:
            return None

        keys = [
            "Entry_Number",
            "Name",
            "EID_Vector",
            "Token_Timestamp",
            "TokenID",
            "Image1Path",
            "Image2Path",
            "Booth_Number"
        ]

        return dict(zip(keys, row))

    def stage_token(self, entry_number, token_id, issued_at, img1, img2, booth):
        """Write token data to the LOCAL SQLite database (device audit trail)."""
        conn = sqlite3.connect(self.db_path)
        cur  = conn.cursor()

        cur.execute(
            """
            UPDATE voters
            SET TokenID=?,
                Token_Timestamp=?,
                Image1Path=?,
                Image2Path=?,
                Booth_Number=?
            WHERE Entry_Number=?
            """,
            (token_id, issued_at, img1, img2, str(booth), entry_number)
        )

        conn.commit()
        conn.close()

    # ══════════════════════════════════════════════════════════════════
    #  REMOTE SERVER API (cross-device synchronisation)
    # ══════════════════════════════════════════════════════════════════

    def _configure_tls(self):
        """Set up TLS client certificates on the requests session."""
        if not DISABLE_TLS and os.path.isfile(CLIENT_CERT) and os.path.isfile(CLIENT_KEY):
            self.session.cert = (CLIENT_CERT, CLIENT_KEY)
            if os.path.isfile(CA_CERT):
                self.session.verify = CA_CERT
            else:
                print(f"Warning: CA certificate not found at {CA_CERT}, using system CA bundle")
        elif DISABLE_TLS:
            self.session.verify = False
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        else:
            print("Warning: Client TLS certificates not found. Requests may fail in production.")

    def _api_url(self, path: str) -> str:
        return f"{self.base_url}/api{path}"

    def _get_voter_remote(self, entry_number: str):
        """Fetch voter status from the central server."""
        endpoint = f"/voter/{entry_number}"
        try:
            resp = self.session.get(self._api_url(endpoint), timeout=10)
            self.journal.log_request("GET", endpoint, resp.status_code,
                                     resp.status_code in (200, 404), entry_number)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.ConnectionError as e:
            self.journal.log_request("GET", endpoint, None, False, entry_number, str(e))
            print(f"ERROR: Cannot reach server at {self.base_url}")
            return None
        except requests.RequestException as e:
            self.journal.log_request("GET", endpoint, None, False, entry_number, str(e))
            print(f"ERROR: get_voter_remote failed: {e}")
            return None

    # ══════════════════════════════════════════════════════════════════
    #  PUBLIC API (used by app.py)
    # ══════════════════════════════════════════════════════════════════

    def get_voter_local(self, entry_number: str):
        """Fetch voter ONLY from the local database (used for instant UI)."""
        return self._get_voter_local(entry_number)

    def sync_voter_remote(self, local: dict) -> dict:
        """
        Check central server for token generation status.
        Adds _server_status and _server_device keys to the dictionary.
        """
        remote = self._get_voter_remote(local["Entry_Number"])

        if remote is not None:
            server_status = remote.get("status", "not_generated")

            # Reflect server state into local dict
            if server_status.startswith("generated_at_device_"):
                local["TokenID"]      = remote.get("token_id")     or local.get("TokenID")
                local["Booth_Number"] = remote.get("booth_number") or local.get("Booth_Number")

            local["_server_status"] = server_status
            local["_server_device"] = remote.get("device_id")
        else:
            local["_server_status"] = None
            local["_server_device"] = None

        return local

    def has_token(self, voter: dict) -> bool:
        """
        Check if the voter has already been issued a token.
        Server is authoritative; falls back to local SQLite if unreachable.
        """
        server_status = voter.get("_server_status")
        if server_status is not None:
            return server_status.startswith("generated_at_device_")
        return voter.get("TokenID") is not None

    def is_in_progress(self, voter: dict) -> bool:
        """Check if token generation is in progress on ANOTHER device."""
        server_status = voter.get("_server_status", "")
        if server_status and server_status.startswith("requested_by_device_"):
            requesting_device = server_status.replace("requested_by_device_", "")
            return requesting_device != self.device_id
        return False

    def request_token(self, entry_number: str, regenerate: bool = False) -> tuple:
        """
        Request permission from the central server to generate a token.

        On success, immediately writes a safety-cancel entry to
        unsynced_requests.json so a power failure before the RFID write
        completes will cause a cancel to be sent on the next reboot.

        Returns: (success: bool, message: str)
        """
        suffix   = "/regenerate" if regenerate else "/request"
        endpoint = f"/voter/{entry_number}{suffix}"
        try:
            resp = self.session.post(
                self._api_url(endpoint),
                json={"device_id": self.device_id},
                timeout=10,
            )
            success = resp.status_code == 200
            self.journal.log_request("POST", endpoint, resp.status_code, success, entry_number)

            if success:
                # Write safety-cancel immediately — survives power failure
                self.journal.add_safety_cancel(entry_number)
                return True, "approved"

            if resp.status_code == 409:
                data           = resp.json()
                current_status = data.get("current_status", "unknown")
                if current_status.startswith("requested_by_device_"):
                    device = current_status.replace("requested_by_device_", "")
                    return False, f"Already being processed by Device {device}"
                if current_status.startswith("generated_at_device_"):
                    device = current_status.replace("generated_at_device_", "")
                    return False, f"Token already generated at Device {device}"
                return False, data.get("error", "Conflict")

            if resp.status_code == 404:
                return False, "Voter not found on central server"

            return False, f"Server error ({resp.status_code})"

        except requests.ConnectionError as e:
            self.journal.log_request("POST", endpoint, None, False, entry_number, str(e))
            return False, f"Cannot reach server at {self.base_url}"
        except requests.RequestException as e:
            self.journal.log_request("POST", endpoint, None, False, entry_number, str(e))
            return False, str(e)

    def mark_rfid_written(self, entry_number: str, token_id: str, booth: int):
        """
        Call this immediately after a successful RFID card write, before
        starting the confirm retry loop.

        Atomically promotes the safety-cancel entry to a pending-confirm
        entry in unsynced_requests.json.  If the device reboots before
        confirm succeeds the confirm will be replayed automatically.
        """
        self.journal.promote_to_confirm(entry_number, token_id, booth)
        self.journal.log_request(
            "LOCAL", f"/voter/{entry_number}/rfid_written", "LOCAL", True,
            entry_number, f"booth={booth} token={token_id}"
        )

    def confirm_token(self, entry_number: str, token_id: str, booth: int) -> bool:
        """
        Notify the central server that token generation succeeded.

        On failure: persists a confirm entry to unsynced_requests.json so
        the confirm is replayed on the next startup.

        Returns True on success, False on failure.
        """
        endpoint = f"/voter/{entry_number}/confirm"
        try:
            resp = self.session.post(
                self._api_url(endpoint),
                json={
                    "device_id":    self.device_id,
                    "token_id":     token_id,
                    "booth_number": str(booth),
                },
                timeout=10,
            )
            success = resp.status_code == 200
            self.journal.log_request("POST", endpoint, resp.status_code, success, entry_number)

            if success:
                # All pending journal entries for this voter are now resolved
                self.journal.resolve_voter(entry_number)
                return True

            # Persist so it survives a reboot
            print(f"WARNING: confirm_token failed ({resp.status_code}): {resp.text}")
            self.journal.ensure_confirm(entry_number, token_id, booth)
            return False

        except requests.RequestException as e:
            self.journal.log_request("POST", endpoint, None, False, entry_number, str(e))
            print(f"ERROR: confirm_token failed: {e}")
            self.journal.ensure_confirm(entry_number, token_id, booth)
            return False

    def cancel_token(self, entry_number: str) -> bool:
        """
        Notify the central server that token generation failed.
        Releases the lock so another device (or retry) can claim this voter.

        On failure: persists a cancel entry to unsynced_requests.json so
        the cancel is replayed on the next startup.

        Returns True on success, False on failure.
        """
        endpoint = f"/voter/{entry_number}/cancel"
        try:
            resp = self.session.post(
                self._api_url(endpoint),
                json={"device_id": self.device_id},
                timeout=10,
            )
            success = resp.status_code == 200
            self.journal.log_request("POST", endpoint, resp.status_code, success, entry_number)

            if success:
                self.journal.resolve_voter(entry_number)
                return True

            print(f"WARNING: cancel_token failed ({resp.status_code}): {resp.text}")
            self.journal.ensure_cancel(entry_number)
            return False

        except requests.RequestException as e:
            self.journal.log_request("POST", endpoint, None, False, entry_number, str(e))
            print(f"ERROR: cancel_token failed: {e}")
            self.journal.ensure_cancel(entry_number)
            return False

    def rotate_files_and_reinitialize(self) -> tuple:
        """Rotate voters.db and Electoral_Roll.csv to logs/ dir, fetch new Electoral_Roll.csv, and reinitialize db."""
        import datetime
        import shutil

        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = os.path.join(".", "logs", f"cycle_{now_str}")
        os.makedirs(log_dir, exist_ok=True)

        if os.path.exists(self.db_path):
            shutil.move(self.db_path, os.path.join(log_dir, "voters.db"))

        if os.path.exists(ELECTORAL_ROLL_PATH):
            shutil.move(ELECTORAL_ROLL_PATH, os.path.join(log_dir, "Electoral_Roll.csv"))

        try:
            resp = self.session.get(self._api_url("/electoral_roll"), timeout=30)
            resp.raise_for_status()
            with open(ELECTORAL_ROLL_PATH, "wb") as f:
                f.write(resp.content)
        except requests.RequestException as e:
            return False, f"Failed to fetch new electoral roll: {e}"

        self._ensure_db()
        return True, "Successfully reset for a new election cycle."
