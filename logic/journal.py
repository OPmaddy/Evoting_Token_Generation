"""
Request Journal — Device-side audit log and crash-recovery queue.

Two persistent artefacts are maintained:

    logs/requests.log          Append-only, flushed immediately after every API
                               attempt.  Contains timestamp, method, endpoint,
                               HTTP status, voter entry, and success/failure.

    unsynced_requests.json     Pending *critical* requests that must be
                               replayed on the next startup if they were not
                               resolved during the current run (e.g. power
                               failure, network outage).

Unsynced entry types
--------------------
    "cancel"   — server lock must be released (failure path, or safety net
                 immediately after request_token succeeds to cover power-off
                 before RFID write outcome is known).

    "confirm"  — RFID card was already written; confirmation to server is
                 mandatory.  Written as soon as the card write succeeds so it
                 survives a reboot.

Replay priority on startup
--------------------------
    1. CONFIRM entries  (card written — confirming prevents duplicate issue)
    2. CANCEL  entries  (release stale server lock)

Within each group entries are replayed oldest-first.
"""

import os
import json
import uuid
import threading
from datetime import datetime, timezone


_write_lock = threading.Lock()


class RequestJournal:
    """
    Thread-safe journal of API requests.

    The unsynced file is written atomically (write to .tmp, then os.replace)
    so a half-written file on power loss cannot corrupt the queue.
    Every write is immediately fsync'd for durability on Raspberry Pi SD cards.
    """

    def __init__(self, journal_dir: str = "logs", unsynced_path: str = "unsynced_requests.json"):
        self.journal_dir   = journal_dir
        self.log_path      = os.path.join(journal_dir, "requests.log")
        self.unsynced_path = unsynced_path

        os.makedirs(journal_dir, exist_ok=True)

        # Initialise unsynced file if absent
        if not os.path.exists(unsynced_path):
            self._write_unsynced([])

    # ── Internal helpers ────────────────────────────────────────────────────

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _read_unsynced(self) -> list:
        try:
            with open(self.unsynced_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _write_unsynced(self, entries: list):
        """Write the unsynced queue atomically with fsync for crash safety."""
        tmp = self.unsynced_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.unsynced_path)  # atomic on POSIX and Windows

    # ── Append-only request log ─────────────────────────────────────────────

    def log_request(
        self,
        method: str,
        endpoint: str,
        response_code,          # int or None if no response received
        success: bool,
        entry_number: str = None,
        detail: str = None,
    ):
        """
        Append one line to requests.log and flush to disk immediately.
        Called for every outgoing API attempt, whether or not it succeeds.
        """
        ts         = self._now()
        code_str   = str(response_code) if response_code is not None else "NO_RESP"
        result_str = "OK  " if success else "FAIL"
        voter_str  = f" voter={entry_number}" if entry_number else ""
        detail_str = f" | {detail}"          if detail       else ""
        line       = (
            f"[{ts}] {result_str} {method:4s} {endpoint}"
            f" ({code_str}){voter_str}{detail_str}\n"
        )
        with _write_lock:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())

    # ── Unsynced queue management ───────────────────────────────────────────

    def add_safety_cancel(self, entry_number: str) -> str:
        """
        Add a safety-cancel entry immediately after request_token() succeeds.

        This is a power-failure safety net: if the device dies before the
        RFID write result is known, the reboot will send a cancel so the
        voter's server lock is released and they can be re-processed.

        Returns the entry ID (a UUID string).
        """
        with _write_lock:
            entries = self._read_unsynced()
            # Idempotent — don't duplicate for the same voter
            for e in entries:
                if e["entry_number"] == entry_number and e["type"] == "cancel":
                    return e["id"]
            entry = {
                "id":           str(uuid.uuid4()),
                "type":         "cancel",
                "reason":       "safety_cancel",
                "entry_number": entry_number,
                "created_at":   self._now(),
                "attempts":     0,
            }
            entries.append(entry)
            self._write_unsynced(entries)
            return entry["id"]

    def promote_to_confirm(self, entry_number: str, token_id: str, booth: int) -> str:
        """
        Called immediately after a successful RFID write.

        Atomically:
          1. Adds a 'confirm' entry with the token payload.
          2. Removes the safety_cancel for the same voter.

        The confirm entry is written BEFORE the cancel is removed, so if
        power fails between the two operations, both entries exist and the
        replay logic (confirms take priority) will still confirm correctly.

        Returns the confirm entry ID.
        """
        with _write_lock:
            entries = self._read_unsynced()
            # Idempotent
            for e in entries:
                if e["entry_number"] == entry_number and e["type"] == "confirm":
                    return e["id"]
            confirm_entry = {
                "id":           str(uuid.uuid4()),
                "type":         "confirm",
                "reason":       "rfid_written_pending_confirm",
                "entry_number": entry_number,
                "token_id":     token_id,
                "booth":        booth,
                "created_at":   self._now(),
                "attempts":     0,
            }
            # Remove any cancel entries for this voter, add confirm
            entries = [
                e for e in entries
                if not (e["entry_number"] == entry_number and e["type"] == "cancel")
            ]
            entries.append(confirm_entry)
            self._write_unsynced(entries)
            return confirm_entry["id"]

    def ensure_confirm(self, entry_number: str, token_id: str, booth: int) -> str:
        """
        Ensure a pending confirm entry exists in the unsynced queue.
        Called when confirm_token() fails so the entry survives a reboot.
        Idempotent — will not create a duplicate if one already exists.
        Returns the entry ID.
        """
        with _write_lock:
            entries = self._read_unsynced()
            for e in entries:
                if e["entry_number"] == entry_number and e["type"] == "confirm":
                    return e["id"]
            entry = {
                "id":           str(uuid.uuid4()),
                "type":         "confirm",
                "reason":       "confirm_failed",
                "entry_number": entry_number,
                "token_id":     token_id,
                "booth":        booth,
                "created_at":   self._now(),
                "attempts":     0,
            }
            entries.append(entry)
            self._write_unsynced(entries)
            return entry["id"]

    def ensure_cancel(self, entry_number: str) -> str:
        """
        Ensure a pending cancel entry exists in the unsynced queue.
        Called when cancel_token() fails — the lock must be released eventually.
        Replaces any existing cancel entry for this voter to avoid duplicates.
        Returns the entry ID.
        """
        with _write_lock:
            entries = self._read_unsynced()
            # Remove existing cancel entries, then add one fresh
            entries = [
                e for e in entries
                if not (e["entry_number"] == entry_number and e["type"] == "cancel")
            ]
            entry = {
                "id":           str(uuid.uuid4()),
                "type":         "cancel",
                "reason":       "cancel_failed",
                "entry_number": entry_number,
                "created_at":   self._now(),
                "attempts":     0,
            }
            entries.append(entry)
            self._write_unsynced(entries)
            return entry["id"]

    def resolve_voter(self, entry_number: str):
        """
        Remove ALL unsynced entries for a voter.
        Called when cancel OR confirm succeeds — the voter is fully settled.
        """
        with _write_lock:
            entries = self._read_unsynced()
            entries = [e for e in entries if e["entry_number"] != entry_number]
            self._write_unsynced(entries)

    def increment_attempts(self, entry_id: str):
        """Increment the attempt counter for an unsynced entry."""
        with _write_lock:
            entries = self._read_unsynced()
            for e in entries:
                if e["id"] == entry_id:
                    e["attempts"]     = e.get("attempts", 0) + 1
                    e["last_attempt"] = self._now()
                    break
            self._write_unsynced(entries)

    def get_pending(self) -> list:
        """
        Return all unsynced entries sorted by priority:
        confirms first (RFID already written), then cancels.
        Within each group: oldest first.
        """
        entries = self._read_unsynced()
        confirms = sorted(
            [e for e in entries if e["type"] == "confirm"],
            key=lambda x: x.get("created_at", "")
        )
        cancels = sorted(
            [e for e in entries if e["type"] == "cancel"],
            key=lambda x: x.get("created_at", "")
        )
        return confirms + cancels

    def has_pending(self) -> bool:
        return bool(self._read_unsynced())
