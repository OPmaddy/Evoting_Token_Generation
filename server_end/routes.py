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

from flask import Blueprint, request, jsonify, send_file
import os
import json
import base64
from datetime import datetime
from werkzeug.utils import secure_filename
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

# ─── Regenerate Token (Admin) ─────────────────────────────────────────────────

@api.route("/voter/<entry_number>/regenerate", methods=["POST"])
def regenerate_token(entry_number: str):
    """
    Force a token regeneration for a voter.
    Body: { "device_id": "1" }
    """
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id")

    if not device_id:
        return jsonify({"error": "device_id is required"}), 400

    existing = voters.get_voter(entry_number)
    if existing is None:
        return jsonify({"error": "Voter not found"}), 404

    result = voters.regenerate_token(entry_number, str(device_id))
    if result is None:
        return jsonify({"error": "Failed to regenerate token"}), 500

    return jsonify({
        "message": f"Token regeneration approved for device {device_id}",
        "voter": result,
    }), 200

# ─── Fetch Electoral Roll ─────────────────────────────────────────────────────

@api.route("/electoral_roll", methods=["GET"])
def get_electoral_roll():
    """Download the new Electoral_Roll.csv for the next cycle"""
    file_path = os.path.join(os.path.dirname(__file__), "..", "Electoral_Roll.csv")
    if not os.path.exists(file_path):
        return jsonify({"error": "Electoral_Roll.csv not found on server"}), 404
    return send_file(file_path, as_attachment=True, download_name="Electoral_Roll.csv")


# ─── Admin: List All Voters ───────────────────────────────────────────────────

@api.route("/voters", methods=["GET"])
def list_voters():
    """Admin endpoint — return all voters and their current statuses."""
    all_voters = voters.get_all_voters()
    return jsonify({
        "count": len(all_voters),
        "voters": all_voters,
    }), 200


# ─── Device Re-Initialization (Master Sync) ───────────────────────────────────

@api.route("/device/<device_id>/reinit", methods=["GET"])
def device_reinit(device_id: str):
    """
    Fetch all configurations and pre-existing certificates for re-initialization.
    Assumes pre-existing certificates exist; otherwise throws an error.
    """
    base_dir = os.path.dirname(__file__)
    
    # 1. Fetch TLS Certificates
    certs_dir = os.path.join(base_dir, "all_certs", f"device_{device_id}", "certs")
    if not os.path.exists(certs_dir):
        return jsonify({"error": f"Pre-existing certificates for device_{device_id} not found. Cannot re-initialize."}), 404
        
    try:
        with open(os.path.join(certs_dir, "ca.crt"), "r") as f: ca_crt = f.read()
        with open(os.path.join(certs_dir, f"device_{device_id}.crt"), "r") as f: dev_crt = f.read()
        with open(os.path.join(certs_dir, f"device_{device_id}.key"), "r") as f: dev_key = f.read()
    except Exception as e:
        return jsonify({"error": f"Failed to read certificates: {str(e)}"}), 500

    # 2. Fetch Election Config (End time and allowed BMDs)
    config_path = os.path.join(base_dir, "election_config.json")
    election_end_time = None
    allowed_bmds = []
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
                election_end_time = config.get("election_end_time")
                allowed_bmds = config.get("master_allowed_bmds", {}).get(device_id, [1])
        except Exception:
            pass
            
    # 3. Fetch BMD Keys
    bmd_keys_path = os.path.join(base_dir, "..", "bmd_keys.json")
    bmd_keys = {}
    if os.path.exists(bmd_keys_path):
        try:
            with open(bmd_keys_path, "r") as f:
                bmd_keys = json.load(f)
        except Exception:
            pass

    # 4. Fetch Electoral Roll (Base64 encoded)
    csv_path = os.path.join(base_dir, "..", "Electoral_Roll.csv")
    electoral_roll_b64 = ""
    if os.path.exists(csv_path):
        try:
            with open(csv_path, "rb") as f:
                electoral_roll_b64 = base64.b64encode(f.read()).decode('utf-8')
        except Exception:
            pass

    return jsonify({
        "status": "success",
        "certificates": {
            "ca_crt": ca_crt,
            "device_crt": dev_crt,
            "device_key": dev_key
        },
        "config": {
            "election_end_time": election_end_time,
            "allowed_bmds": allowed_bmds,
            "bmd_keys": bmd_keys,
            "electoral_roll_b64": electoral_roll_b64
        }
    }), 200


# ─── Upload Device Logs (End Election) ────────────────────────────────────────

@api.route("/device/<device_id>/logs", methods=["POST"])
def upload_device_logs(device_id: str):
    """
    Receives compressed/raw log files from a device when it ends elections or reinitializes.
    """
    if 'log' not in request.files:
        return jsonify({"error": "No log file provided in 'log' field"}), 400
        
    file = request.files['log']
    if file.filename == '':
        return jsonify({"error": "Empty filename"}), 400
        
    logs_dir = os.path.join(os.path.dirname(__file__), "device_logs")
    os.makedirs(logs_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_filename = secure_filename(file.filename)
    final_filename = f"device_{device_id}_{timestamp}_{safe_filename}"
    
    file_path = os.path.join(logs_dir, final_filename)
    try:
        file.save(file_path)
        return jsonify({"status": "success", "message": f"Log saved to {final_filename}"}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to save log: {str(e)}"}), 500

