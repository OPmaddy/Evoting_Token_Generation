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

from datetime import datetime, timezone
from pymongo import MongoClient, ReturnDocument
from config import (
    MONGO_URI,
    MONGO_DB_NAME,
    MONGO_COLLECTION,
)


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

    # ── public API ─────────────────────────────────────────────────────────

    def get_voter(self, entry_number: str) -> dict | None:
        """
        Look up a voter by entry number (case-insensitive).

        Intentionally a pure read — does NOT modify the document.
        Stale lock detection is left to the admin/regenerate flow.
        """
        doc = self.collection.find_one(
            {"entry_number": {"$regex": f"^{entry_number}$", "$options": "i"}}
        )
        return self._serialize(doc)

    def request_token(self, entry_number: str, device_id: str) -> dict | None:
        """
        Atomically claim a voter for token generation.

        Succeeds ONLY if the current status is exactly "not_generated".
        Any other state (in-progress on another device, already generated)
        returns None so the caller gets a 409.

        The MongoDB find_one_and_update is atomic at the document level,
        so two simultaneous requests for the same voter cannot both succeed.
        """
        now = datetime.now(timezone.utc).isoformat()
        doc = self.collection.find_one_and_update(
            {
                "entry_number": {"$regex": f"^{entry_number}$", "$options": "i"},
                "status": "not_generated",
            },
            {
                "$set": {
                    "status": f"requested_by_device_{device_id}",
                    "device_id": device_id,
                    "requested_at": now,
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

    def regenerate_token(self, entry_number: str, device_id: str) -> dict | None:
        """
        Force a voter into a requested state regardless of current status.
        Used by admins to unlock a stuck voter (stale lock, hardware failure, etc.).
        Logs the previous state to an append-only audit file.
        """
        import os
        existing = self.collection.find_one(
            {"entry_number": {"$regex": f"^{entry_number}$", "$options": "i"}}
        )
        if existing:
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
