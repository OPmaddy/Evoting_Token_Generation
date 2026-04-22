"""
MongoDB models for voter token status management.

Voter document schema:
{
    "entry_number": str,         # primary identifier (unique index)
    "name": str,
    "eid_vector": str,           # semicolon-separated election IDs
    "status": str,               # "not_generated" | "requested_by_device_<X>" | "generated_at_device_<X>"
    "device_id": str | None,     # device that currently owns the request
    "token_id": str | None,
    "token_timestamp": str | None,
    "booth_number": str | None,
    "requested_at": str | None,  # ISO timestamp when request was made
    "generated_at": str | None   # ISO timestamp when token was generated
}

Lock lifecycle
--------------
not_generated  ──request_token()──►  requested_by_device_<X>
                                          │
                         ┌────────────────┴──────────────────┐
               confirm_token()                          cancel_token()
                          │                                   │
             generated_at_device_<X>               not_generated

Stale locks ("requested_by_device_*" that never resolved) are NOT auto-cleared
by this module.  They must be resolved by an admin using the regenerate flow
or cancel flow.  This eliminates the race condition where a passive GET could
silently steal a live device's lock.
"""
import os
import threading
from datetime import datetime, timezone
from pymongo import MongoClient, ReturnDocument
from config import (
    MONGO_URI,
    MONGO_DB_NAME,
    MONGO_COLLECTION,
)
import random
import os
import math


# Global lock for thread-safe file logging
log_lock = threading.Lock()

class VoterCollection:
    """Thread-safe wrapper around the voters MongoDB collection."""

    def __init__(self):
        self.client = MongoClient(MONGO_URI)
        self.db = self.client[MONGO_DB_NAME]
        self.collection = self.db[MONGO_COLLECTION]

        # Ensure unique index on entry_number
        self.collection.create_index("entry_number", unique=True)

    # ── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _serialize(doc: dict) -> dict:
        """Remove the internal MongoDB _id for JSON-safe output."""
        if doc is None:
            return None
        doc = dict(doc)
        doc.pop("_id", None)
        return doc

    @staticmethod
    def _log_booth(line: str):
        """Append a line to booth_allotment.log immediately."""
        log_path = os.path.join(os.path.dirname(__file__), "logs", "booth_allotment.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        with log_lock:
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"[{ts}] {line}\n")
                    f.flush()
                    os.fsync(f.fileno())
            except Exception as exc:
                print(f"[booth_log] {exc}")

    # ── public API ─────────────────────────────────────────────────────────

    def get_voter(self, entry_number: str) -> dict | None:
        """
        Look up a voter by entry number (case-insensitive).
        Intentionally a pure read — does NOT modify the document.
        """
        doc = self.collection.find_one(
            {"entry_number": {"$regex": f"^{entry_number}$", "$options": "i"}}
        )
        return self._serialize(doc)

    def allot_booth(self, allowed_booths: list[int], entry_number: str) -> int:
        """
        Pick the least-occupied booth from allowed_booths using time-decay.
        Tie-breaker: Prefer booths with lower lifetime usage (total history).
        Returns the chosen booth number (int).
        """
        now = datetime.now(timezone.utc)

        # 1. Fetch current active docs for time-decay occupancy
        active_docs = list(self.collection.find(
            {
                "booth_number": {"$in": [str(b) for b in allowed_booths]},
                "status": {"$not": {"$eq": "not_generated"}},
            },
            {"booth_number": 1, "booth_allotted_at": 1}
        ))

        occupancy = {b: 0.0 for b in allowed_booths}
        for doc in active_docs:
            try:
                b_str = doc.get("booth_number")
                b = int(b_str)
                if b not in occupancy: continue
            except: continue

            allotted_str = doc.get("booth_allotted_at")
            if allotted_str:
                try:
                    allotted = datetime.fromisoformat(allotted_str)
                    if allotted.tzinfo is None: allotted = allotted.replace(tzinfo=timezone.utc)
                    elapsed_minutes = (now - allotted).total_seconds() / 60.0
                    occupancy[b] += max(0.0, 1.0 - elapsed_minutes)
                except: occupancy[b] += 1.0
            else: occupancy[b] += 1.0

        # 2. Fetch lifetime usage (total allotments) for tie-breaking
        lifetime_usage = {b: 0 for b in allowed_booths}
        usage_data = list(self.collection.aggregate([
            {"$match": {"booth_number": {"$in": [str(b) for b in allowed_booths]}}},
            {"$group": {"_id": "$booth_number", "count": {"$sum": 1}}}
        ]))
        for item in usage_data:
            try:
                b = int(item["_id"])
                if b in lifetime_usage: lifetime_usage[b] = item["count"]
            except: continue

        # 3. Decision logic: Min occupancy first, then min lifetime
        min_occ = min(occupancy.values())
        candidates = [b for b, occ in occupancy.items() if math.isclose(occ, min_occ, abs_tol=0.01)]
        
        if len(candidates) > 1:
            min_life = min(lifetime_usage[b] for b in candidates)
            final_candidates = [b for b in candidates if lifetime_usage[b] == min_life]
            chosen = random.choice(final_candidates)
        else:
            chosen = candidates[0]

        occ_summary = ", ".join(f"B{b}={occupancy[b]:.2f}(L:{lifetime_usage[b]})" for b in sorted(allowed_booths))
        self._log_booth(f"ALLOT voter={entry_number} booth={chosen} | {occ_summary} | candidates={candidates}")
        return chosen

    def get_booth_occupancy(self, all_booths: list[int]) -> dict:
        """
        Return estimated current occupancy AND lifetime usage per booth.
        Used by the admin dashboard for live traffic monitoring.
        Returns { "occupancy": {str: float}, "lifetime": {str: int} }
        """
        now = datetime.now(timezone.utc)
        active_docs = list(self.collection.find(
            {
                "booth_number": {"$in": [str(b) for b in all_booths]},
                "status": {"$not": {"$eq": "not_generated"}},
            },
            {"booth_number": 1, "booth_allotted_at": 1}
        ))

        occ = {str(b): 0.0 for b in all_booths}
        for doc in active_docs:
            b_str = doc.get("booth_number")
            if b_str not in occ: continue
            
            allotted_str = doc.get("booth_allotted_at")
            if allotted_str:
                try:
                    allotted = datetime.fromisoformat(allotted_str)
                    if allotted.tzinfo is None: allotted = allotted.replace(tzinfo=timezone.utc)
                    elapsed_minutes = (now - allotted).total_seconds() / 60.0
                    occ[b_str] += max(0.0, 1.0 - elapsed_minutes)
                except: occ[b_str] += 1.0
            else: occ[b_str] += 1.0

        # Lifetime usage
        life = {str(b): 0 for b in all_booths}
        usage_data = list(self.collection.aggregate([
            {"$match": {"booth_number": {"$in": [str(b) for b in all_booths]}}},
            {"$group": {"_id": "$booth_number", "count": {"$sum": 1}}}
        ]))
        for item in usage_data:
            b_str = item["_id"]
            if b_str in life: life[b_str] = item["count"]

        return {"occupancy": occ, "lifetime": life}

    def request_token(self, entry_number: str, device_id: str, allowed_booths: list[int]) -> dict | None:
        """
        Atomically claim a voter for token generation AND allot a booth.

        allowed_booths must be non-empty; the server picks the least-occupied
        booth using time-decay occupancy and includes it in the document.

        Succeeds ONLY if the current status is exactly "not_generated".
        Returns the updated document (including booth_number) on success,
        or None if the voter could not be claimed.
        """
        if not allowed_booths:
            return None

        booth = self.allot_booth(allowed_booths, entry_number)
        now   = datetime.now(timezone.utc).isoformat()

        doc = self.collection.find_one_and_update(
            {
                "entry_number": {"$regex": f"^{entry_number}$", "$options": "i"},
                "status": "not_generated",
            },
            {
                "$set": {
                    "status":           f"requested_by_device_{device_id}",
                    "device_id":        device_id,
                    "requested_at":     now,
                    "booth_number":     str(booth),
                    "booth_allotted_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return self._serialize(doc)

    def confirm_token(
        self,
        entry_number: str,
        device_id: str,
        token_id: str,
        booth_number: str,
    ) -> dict | None:
        """
        Mark a voter's token as successfully generated.

        Succeeds only if the current status is "requested_by_device_<device_id>".
        Returns None if the voter is not in the expected state for this device.
        """
        now = datetime.now(timezone.utc).isoformat()
        doc = self.collection.find_one_and_update(
            {
                "entry_number": {"$regex": f"^{entry_number}$", "$options": "i"},
                "status": f"requested_by_device_{device_id}",
            },
            {
                "$set": {
                    "status": f"generated_at_device_{device_id}",
                    "token_id": token_id,
                    "token_timestamp": now,
                    "booth_number": booth_number,
                    "generated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        
        if doc:
            # Central log of issuance (who got what)
            audit_log_path = os.path.join(os.path.dirname(__file__), "issuance_audit.log")
            with log_lock:
                try:
                    with open(audit_log_path, "a", encoding="utf-8") as f:
                        is_regen = doc.get("is_regenerated", False)
                        log_line = f"[{now}] ISSUED: voter={entry_number} device={device_id} token={token_id} booth={booth_number} regen={is_regen}\n"
                        f.write(log_line)
                except Exception as exc:
                    print(f"[audit_log] {exc}")

        return self._serialize(doc)

    def cancel_token(self, entry_number: str, device_id: str) -> dict | None:
        """
        Release a token request back to "not_generated".

        Succeeds only if the current status is "requested_by_device_<device_id>".
        This is safe to call on any error path — if the status has already
        changed (e.g. another admin action ran), it returns None silently.
        """
        doc = self.collection.find_one_and_update(
            {
                "entry_number": {"$regex": f"^{entry_number}$", "$options": "i"},
                "status": f"requested_by_device_{device_id}",
            },
            {
                "$set": {
                    "status": "not_generated",
                    "device_id": None,
                    "requested_at": None,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return self._serialize(doc)

    def regenerate_token(self, entry_number: str, device_id: str, allowed_booths: list[int]) -> dict | None:
        """
        Force a voter into a requested state regardless of current status.
        Used by admins to unlock a stuck voter (stale lock, hardware failure, etc.).
        Logs the previous state to an append-only audit file.
        """
        import os
        existing = self.collection.find_one(
            {"entry_number": {"$regex": f"^{entry_number}$", "$options": "i"}}
        )
        if not existing:
            return None

        log_path = os.path.join(os.path.dirname(__file__), "regeneration_audit.log")
        log_line = (
            f"[{datetime.now(timezone.utc).isoformat()}] REGENERATE TRIGGERED FOR {entry_number} "
            f"| Old Status: {existing.get('status')} "
            f"| Old Device: {existing.get('device_id')} "
            f"| Old Token ID: {existing.get('token_id')} "
            f"| Old Requested At: {existing.get('requested_at')} "
            f"| Old Generated At: {existing.get('generated_at')}\n"
        )
        with open(log_path, "a") as f:
            f.write(log_line)

        # Re-allot a booth for the new attempt
        booth = self.allot_booth(allowed_booths, entry_number)
        now = datetime.now(timezone.utc).isoformat()
        
        doc = self.collection.find_one_and_update(
            {
                "entry_number": {"$regex": f"^{entry_number}$", "$options": "i"}
            },
            {
                "$set": {
                    "status": f"requested_by_device_{device_id}",
                    "device_id": device_id,
                    "requested_at": now,
                    "booth_number": str(booth),
                    "booth_allotted_at": now,
                    "is_regenerated": True
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return self._serialize(doc)

    def get_all_voters(self) -> list[dict]:
        """
        Return all voter documents (admin).
        Pure read — does not modify any documents.
        """
        docs = list(self.collection.find())
        return [self._serialize(doc) for doc in docs]
