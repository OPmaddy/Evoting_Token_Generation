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
"""

from datetime import datetime, timedelta, timezone
from pymongo import MongoClient, ReturnDocument
from config import (
    MONGO_URI,
    MONGO_DB_NAME,
    MONGO_COLLECTION,
    STALE_REQUEST_TIMEOUT_SECONDS,
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

    def _revert_if_stale(self, doc: dict) -> dict:
        """
        If a document is in a "requested_by_device_*" state and the request
        timestamp exceeds the configured timeout, atomically revert it to
        "not_generated" and return the updated document.
        """
        if doc is None:
            return None

        status = doc.get("status", "")
        if not status.startswith("requested_by_device_"):
            return doc

        requested_at_str = doc.get("requested_at")
        if requested_at_str is None:
            return doc

        try:
            requested_at = datetime.fromisoformat(requested_at_str)
            # Make offset-aware if naive
            if requested_at.tzinfo is None:
                requested_at = requested_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return doc

        now = datetime.now(timezone.utc)
        if (now - requested_at) > timedelta(seconds=STALE_REQUEST_TIMEOUT_SECONDS):
            # Atomically revert — only if status hasn't changed since we read it
            reverted = self.collection.find_one_and_update(
                {
                    "entry_number": doc["entry_number"],
                    "status": status,
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
            if reverted is not None:
                return reverted

        return doc

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
        """Look up a voter by entry number (case-insensitive)."""
        doc = self.collection.find_one(
            {"entry_number": {"$regex": f"^{entry_number}$", "$options": "i"}}
        )
        doc = self._revert_if_stale(doc)
        return self._serialize(doc)

    def request_token(self, entry_number: str, device_id: str) -> dict | None:
        """
        Atomically claim a voter for token generation.

        Succeeds only if the current status is "not_generated".
        Returns the updated document on success, or None if the voter
        could not be claimed (already requested / already generated / not found).
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
        Release a token request back to "not_generated" (e.g. face verification failed).

        Succeeds only if the current status is "requested_by_device_<device_id>".
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

    def get_all_voters(self) -> list[dict]:
        """Return all voter documents (admin)."""
        docs = list(self.collection.find())
        # Revert stale entries on the fly
        results = []
        for doc in docs:
            doc = self._revert_if_stale(doc)
            results.append(self._serialize(doc))
        return results
