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
    """

    def __init__(self, db_path=DB_PATH):
        # ── Local SQLite ──────────────────────────────────────────────
        self.db_path = db_path
        self._ensure_db()

        # ── Remote Server ─────────────────────────────────────────────
        self.base_url = SERVER_URL.rstrip("/")
        self.device_id = DEVICE_ID
        self.session = requests.Session()
        self._configure_tls()

    # ══════════════════════════════════════════════════════════════════
    #  LOCAL SQLite (unchanged from original — device audit trail)
    # ══════════════════════════════════════════════════════════════════

    def _ensure_db(self):
        first_time = not os.path.exists(self.db_path)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(SCHEMA)

        # Migration: Ensure Booth_Number column exists
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
        cur = conn.cursor()

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

        if len(row) != len(keys):
            pass

        return dict(zip(keys, row))

    def stage_token(
        self,
        entry_number,
        token_id,
        issued_at,
        img1,
        img2,
        booth
    ):
        """Write token data to the LOCAL SQLite database (device audit trail)."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

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
        try:
            resp = self.session.get(self._api_url(f"/voter/{entry_number}"), timeout=10)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.ConnectionError:
            print(f"ERROR: Cannot reach server at {self.base_url}")
            return None
        except requests.RequestException as e:
            print(f"ERROR: get_voter_remote failed: {e}")
            return None

    # ══════════════════════════════════════════════════════════════════
    #  PUBLIC API (used by app.py)
    # ══════════════════════════════════════════════════════════════════

    def get_voter_local(self, entry_number: str):
        """
        Fetch voter ONLY from the local database (used for instant UI).
        """
        return self._get_voter_local(entry_number)

    def sync_voter_remote(self, local: dict) -> dict:
        """
        Check central server for token generation status.
        Adds _server_status and _server_device keys to the dictionary.
        """
        remote = self._get_voter_remote(local["Entry_Number"])

        if remote is not None:
            server_status = remote.get("status", "not_generated")

            # If the central server says a token was generated, reflect that
            # in the local dict even if the local DB hasn't been updated yet
            if server_status.startswith("generated_at_device_"):
                local["TokenID"] = remote.get("token_id") or local.get("TokenID")
                local["Booth_Number"] = remote.get("booth_number") or local.get("Booth_Number")

            local["_server_status"] = server_status
            local["_server_device"] = remote.get("device_id")
        else:
            # Server unreachable — fall back to local-only data
            local["_server_status"] = None
            local["_server_device"] = None

        return local

    def has_token(self, voter: dict) -> bool:
        """
        Check if the voter has already been issued a token.
        Uses the central server status as the authoritative source.
        Falls back to local SQLite if the server was unreachable.
        """
        server_status = voter.get("_server_status")

        if server_status is not None:
            # Server is authoritative
            return server_status.startswith("generated_at_device_")

        # Fallback: local SQLite
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

        Returns:
            (success: bool, message: str)
        """
        try:
            endpoint = "/regenerate" if regenerate else "/request"
            resp = self.session.post(
                self._api_url(f"/voter/{entry_number}{endpoint}"),
                json={"device_id": self.device_id},
                timeout=10,
            )
            if resp.status_code == 200:
                return True, "approved"
            elif resp.status_code == 409:
                data = resp.json()
                current_status = data.get("current_status", "unknown")
                if current_status.startswith("requested_by_device_"):
                    device = current_status.replace("requested_by_device_", "")
                    return False, f"Already being processed by Device {device}"
                elif current_status.startswith("generated_at_device_"):
                    device = current_status.replace("generated_at_device_", "")
                    return False, f"Token already generated at Device {device}"
                return False, data.get("error", "Conflict")
            elif resp.status_code == 404:
                return False, "Voter not found on central server"
            else:
                return False, f"Server error ({resp.status_code})"
        except requests.ConnectionError:
            return False, f"Cannot reach server at {self.base_url}"
        except requests.RequestException as e:
            return False, str(e)

    def confirm_token(self, entry_number: str, token_id: str, booth: int) -> bool:
        """
        Notify the central server that token generation succeeded.
        Returns True on success, False on failure.
        """
        try:
            resp = self.session.post(
                self._api_url(f"/voter/{entry_number}/confirm"),
                json={
                    "device_id": self.device_id,
                    "token_id": token_id,
                    "booth_number": str(booth),
                },
                timeout=10,
            )
            if resp.status_code == 200:
                return True
            print(f"WARNING: confirm_token failed ({resp.status_code}): {resp.text}")
            return False
        except requests.RequestException as e:
            print(f"ERROR: confirm_token failed: {e}")
            return False

    def cancel_token(self, entry_number: str) -> bool:
        """
        Notify the central server that token generation failed.
        Releases the lock so another device (or retry) can claim this voter.
        """
        try:
            resp = self.session.post(
                self._api_url(f"/voter/{entry_number}/cancel"),
                json={"device_id": self.device_id},
                timeout=10,
            )
            if resp.status_code == 200:
                return True
            print(f"WARNING: cancel_token failed ({resp.status_code}): {resp.text}")
            return False
        except requests.RequestException as e:
            print(f"ERROR: cancel_token failed: {e}")
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

