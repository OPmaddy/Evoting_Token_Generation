"""
REST API routes for multi-device token generation coordination.

Endpoints
---------
GET   /api/health                         Health check
GET   /api/voter/<entry_number>           Lookup voter + current status
POST  /api/voter/<entry_number>/request   Claim voter for token generation
POST  /api/voter/<entry_number>/confirm   Report successful generation
POST  /api/voter/<entry_number>/cancel    Report failure / release lock
GET   /api/voters                         Admin: list all voters
"""

from flask import Blueprint, request, jsonify
from models import VoterCollection

api = Blueprint("api", __name__, url_prefix="/api")

# Shared collection instance — initialised once when the blueprint is first imported.
voters = VoterCollection()


# ─── Health ────────────────────────────────────────────────────────────────────

@api.route("/health", methods=["GET"])
def health():
    """Simple health-check that also verifies MongoDB connectivity."""
    try:
        voters.client.admin.command("ping")
        return jsonify({"status": "ok", "db": "connected"}), 200
    except Exception as exc:
        return jsonify({"status": "error", "db": str(exc)}), 503


# ─── Voter Lookup ──────────────────────────────────────────────────────────────

@api.route("/voter/<entry_number>", methods=["GET"])
def get_voter(entry_number: str):
    """Return voter info and current token-generation status."""
    voter = voters.get_voter(entry_number)
    if voter is None:
        return jsonify({"error": "Voter not found"}), 404
    return jsonify(voter), 200


# ─── Request Token Generation ─────────────────────────────────────────────────

@api.route("/voter/<entry_number>/request", methods=["POST"])
def request_token(entry_number: str):
    """
    A device requests permission to generate a token for this voter.

    Body: { "device_id": "1" }

    Returns 200 on success, 409 if voter is already claimed/generated, 404 if
    voter does not exist.
    """
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id")

    if not device_id:
        return jsonify({"error": "device_id is required"}), 400

    # Check if voter even exists first (for a better error message)
    existing = voters.get_voter(entry_number)
    if existing is None:
        return jsonify({"error": "Voter not found"}), 404

    result = voters.request_token(entry_number, str(device_id))
    if result is None:
        # Atomic claim failed → voter is already claimed or generated
        return jsonify({
            "error": "Token generation already in progress or completed for this voter",
            "current_status": existing.get("status"),
        }), 409

    return jsonify({
        "message": f"Token generation approved for device {device_id}",
        "voter": result,
    }), 200


# ─── Confirm Token Generated ──────────────────────────────────────────────────

@api.route("/voter/<entry_number>/confirm", methods=["POST"])
def confirm_token(entry_number: str):
    """
    A device reports that token generation succeeded.

    Body: { "device_id": "1", "token_id": "...", "booth_number": "2" }
    """
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id")
    token_id = data.get("token_id")
    booth_number = data.get("booth_number")

    if not device_id or not token_id or booth_number is None:
        return jsonify({"error": "device_id, token_id, and booth_number are required"}), 400

    result = voters.confirm_token(
        entry_number,
        str(device_id),
        str(token_id),
        str(booth_number),
    )
    if result is None:
        return jsonify({
            "error": "Cannot confirm — voter is not in a 'requested' state for this device",
        }), 409

    return jsonify({
        "message": "Token generation confirmed",
        "voter": result,
    }), 200


# ─── Cancel / Release Lock ────────────────────────────────────────────────────

@api.route("/voter/<entry_number>/cancel", methods=["POST"])
def cancel_token(entry_number: str):
    """
    A device reports that token generation failed; release the lock.

    Body: { "device_id": "1" }
    """
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id")

    if not device_id:
        return jsonify({"error": "device_id is required"}), 400

    result = voters.cancel_token(entry_number, str(device_id))
    if result is None:
        return jsonify({
            "error": "Cannot cancel — voter is not in a 'requested' state for this device",
        }), 409

    return jsonify({
        "message": "Token request cancelled, voter status reset",
        "voter": result,
    }), 200


# ─── Admin: List All Voters ───────────────────────────────────────────────────

@api.route("/voters", methods=["GET"])
def list_voters():
    """Admin endpoint — return all voters and their current statuses."""
    all_voters = voters.get_all_voters()
    return jsonify({
        "count": len(all_voters),
        "voters": all_voters,
    }), 200
