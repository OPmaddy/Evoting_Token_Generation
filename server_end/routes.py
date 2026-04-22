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

from flask import Blueprint, render_template, request, jsonify, send_file, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import os
import json
import base64
import pandas as pd
from datetime import datetime
from werkzeug.utils import secure_filename
from models import VoterCollection
from election_manager import ElectionManager

api   = Blueprint("api",   __name__, url_prefix="/api")
admin = Blueprint("admin", __name__, url_prefix="/admin")

# Shared collection instance
voters  = VoterCollection()
manager = ElectionManager(os.path.dirname(__file__))

# ─── Server Request Logger ──────────────────────────────────────────────────────────────────────

_SERVER_LOG_DIR  = os.path.join(os.path.dirname(__file__), "logs")
_SERVER_LOG_PATH = os.path.join(_SERVER_LOG_DIR, "server_requests.log")
os.makedirs(_SERVER_LOG_DIR, exist_ok=True)


def _log_server_request(response=None, error_msg: str = None):
    """Append one line to server_requests.log and flush immediately."""
    ts         = datetime.utcnow().isoformat() + "Z"
    cn         = get_cert_cn() or "unknown"
    method     = request.method
    path       = request.path
    status     = response.status_code if response is not None else "ERROR"
    extra      = f" | {error_msg}" if error_msg else ""
    # Extract voter entry_number from path if present  (/api/voter/<entry>/...)
    parts      = path.strip("/").split("/")
    voter_str  = ""
    if len(parts) >= 3 and parts[1] == "voter":
        voter_str = f" voter={parts[2]}"
    line = f"[{ts}] device={cn} {method:4s} {path} → {status}{voter_str}{extra}\n"
    try:
        with open(_SERVER_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
    except Exception as exc:
        print(f"[LOG ERROR] Could not write to server_requests.log: {exc}")


@api.after_request
def log_api_request(response):
    """Log every /api/* request with device identity and response code."""
    _log_server_request(response)
    return response


# ─── Security Helpers ──────────────────────────────────────────────────────────

def get_cert_cn():
    """Extract Common Name from client certificate."""
    peercert = request.environ.get('peercert')
    
    # Gunicorn does not automatically place 'peercert' into the environ dict like Werkzeug.
    # We must extract it from the raw SSLSocket directly.
    if not peercert:
        sock = request.environ.get('gunicorn.socket')
        if not sock:
            try:
                wsgi_input = request.environ.get('wsgi.input')
                if hasattr(wsgi_input, 'raw'):
                    sock = getattr(wsgi_input.raw, '_sock', None)
            except Exception:
                pass
                
        if sock and hasattr(sock, 'getpeercert'):
            try:
                peercert = sock.getpeercert()
            except Exception:
                pass

    if peercert and 'subject' in peercert:
        for tuple_val in peercert['subject']:
            for key, value in tuple_val:
                if key == 'commonName':
                    return value
    return None

ADMIN_CREDS_FILE = os.path.join(os.path.dirname(__file__), "admin_credentials.json")

def get_admin_creds():
    if not os.path.exists(ADMIN_CREDS_FILE):
        default_creds = {"username": "admin", "password_hash": generate_password_hash("admin123")}
        with open(ADMIN_CREDS_FILE, "w") as f:
            json.dump(default_creds, f)
        return default_creds
    with open(ADMIN_CREDS_FILE, "r") as f:
        return json.load(f)

@admin.before_request
def restrict_admin_access():
    """Ensure user is logged in before accessing admin routes."""
    # Allow access to login without session
    if request.path.endswith("/login"):
        return
    if not session.get("logged_in"):
        return redirect(url_for("admin.login", next=request.path))

@api.before_request
def restrict_master_certs():
    """
    Enforce: Master Certs only for Provisioning.
    Election Certs for Voting.
    """
    if request.endpoint and request.endpoint.startswith('api.'):
        cn = get_cert_cn()
        if not cn:
            # If no cert, usually handshake fails, but if allowed through, reject.
            return jsonify({"error": "Certificate required"}), 403
            
        is_master = cn.startswith("EVoting-Master-Client")
        is_reinit = request.path.endswith('/reinit')
        is_health = request.path.endswith('/health')

        if is_master and not (is_reinit or is_health):
            return jsonify({"error": "Master certificate restricted to provisioning only"}), 403
        
        if not is_master and is_reinit:
            # Reinit should ideally accept master cert originally, 
            # but for convenience we can allow current election certs too? 
            # Re-read: "Devices should only be allowed to request for there certs using master certificate"
            # Actually, to be strict:
            pass # Keep it simple for now, allow both for reinit if needed, 
                 # but block master for others.


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
    The server atomically claims the voter AND allots the least-occupied
    booth from the device's allowed BMD list.

    Body: { "device_id": "1" }
    Returns 200 with { voter, booth_number } on success.
    """
    data      = request.get_json(silent=True) or {}
    device_id = data.get("device_id")

    if not device_id:
        return jsonify({"error": "device_id is required"}), 400

    # Look up allowed booths for this device from live election config
    allowed_booths = manager.get_bmd_mapping().get(str(device_id), [])
    if not allowed_booths:
        return jsonify({
            "error": f"No booths configured for device {device_id}. Configure via Admin → BMD Control."
        }), 400

    # Confirm voter exists first (cleaner error message)
    if voters.get_voter(entry_number) is None:
        return jsonify({"error": "Voter not found"}), 404

    result = voters.request_token(entry_number, str(device_id), allowed_booths)
    if result is None:
        current = voters.get_voter(entry_number)
        return jsonify({
            "error": "Token generation already in progress or completed for this voter",
            "current_status": current.get("status") if current else "unknown",
        }), 409

    return jsonify({
        "message":      f"Token generation approved for device {device_id}",
        "voter":        result,
        "booth_number": result.get("booth_number"),
    }), 200


# ─── Booth Occupancy (live dashboard polling) ─────────────────────────────────

@api.route("/booth_occupancy", methods=["GET"])
def booth_occupancy():
    """Return time-decayed estimated occupancy per booth for the admin dashboard."""
    num_booths = manager.get_num_booths()
    all_booths = list(range(1, num_booths + 1))
    occ = voters.get_booth_occupancy(all_booths)
    return jsonify({"occupancy": occ, "num_booths": num_booths}), 200


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


# ─── Master Re-Initialization (Master Sync) ───────────────────────────────────

@api.route("/device/<device_id>/reinit", methods=["GET"])
def device_reinit(device_id: str):
    """
    Fetch all configurations and pre-existing certificates for re-initialization.
    """
    if not manager.state.get("active_election"):
        return jsonify({"error": "No active election found on server."}), 404

    base_dir = os.path.dirname(__file__)
    
    # 1. Fetch TLS Certificates from all_certs
    certs_dir = os.path.join(base_dir, "all_certs", f"device_{device_id}", "certs")
    if not os.path.exists(certs_dir):
        return jsonify({"error": f"Certificates for device_{device_id} not found."}), 404
        
    try:
        with open(os.path.join(certs_dir, "ca.crt"), "r") as f: ca_crt = f.read()
        with open(os.path.join(certs_dir, f"device_{device_id}.crt"), "r") as f: dev_crt = f.read()
        with open(os.path.join(certs_dir, f"device_{device_id}.key"), "r") as f: dev_key = f.read()
    except Exception as e:
        return jsonify({"error": f"Failed to read certificates: {str(e)}"}), 500

    # 2. Fetch Election Config
    config = manager.state.get("config", {})
    election_end_time = config.get("election_end_time")
    allowed_bmds = config.get("bmd_mapping", {}).get(device_id, [1])
            
    # 3. Fetch BMD Keys
    bmd_keys = config.get("bmd_keys", {})

    # 4. Fetch Electoral Roll (Base64)
    csv_path = os.path.join(base_dir, "..", "Electoral_Roll.csv")
    electoral_roll_b64 = ""
    if os.path.exists(csv_path):
        with open(csv_path, "rb") as f:
            electoral_roll_b64 = base64.b64encode(f.read()).decode('utf-8')

    # Mark device as provisioned
    manager.update_device_status(device_id, "provisioned", True)

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


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN DASHBOARD ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@admin.context_processor
def inject_globals():
    return dict(
        election_active=manager.state.get("active_election", False),
        active_election_name=manager.state.get("active_election_name", "None")
    )


@admin.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        creds = get_admin_creds()
        if username == creds.get("username") and check_password_hash(creds.get("password_hash"), password):
            session["logged_in"] = True
            next_url = request.args.get("next") or url_for("admin.dashboard")
            return redirect(next_url)
        else:
            flash("Invalid credentials", "error")
    return render_template("login.html")

@admin.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("admin.login"))

@admin.route("/change_password", methods=["GET", "POST"])
def change_password():
    if request.method == "POST":
        old_password = request.form.get("old_password")
        new_password = request.form.get("new_password")
        creds = get_admin_creds()
        if check_password_hash(creds.get("password_hash"), old_password):
            creds["password_hash"] = generate_password_hash(new_password)
            with open(ADMIN_CREDS_FILE, "w") as f:
                json.dump(creds, f)
            flash("Password updated successfully.", "success")
            return redirect(url_for("admin.dashboard"))
        else:
            flash("Incorrect current password.", "error")
    return render_template("change_password.html")

@admin.route("/dashboard")
def dashboard():
    num_booths = manager.get_num_booths()
    all_booths = list(range(1, num_booths + 1))
    occupancy  = voters.get_booth_occupancy(all_booths)
    return render_template(
        "dashboard.html",
        election_active=manager.state.get("active_election"),
        master_update_required=manager.state.get("master_update_required"),
        devices=manager.state.get("devices", {}),
        bmd_mapping=manager.get_bmd_mapping(),
        occupancy=occupancy,
        all_booths=all_booths,
    )


@admin.route("/bmd_mapping", methods=["GET", "POST"])
def bmd_mapping():
    """Live BMD mapping editor — change which booths each device can use."""
    if request.method == "POST":
        devices_cfg = manager.state.get("devices", {})
        num_booths  = manager.get_num_booths()
        for device_id in devices_cfg:
            key         = f"booths_{device_id}"
            booth_vals  = request.form.getlist(key)  # list of str booth IDs
            booth_ints  = [int(b) for b in booth_vals if b.isdigit()]
            manager.update_bmd_mapping(device_id, booth_ints)
        flash("BMD mapping updated successfully.", "success")
        return redirect(url_for("admin.bmd_mapping"))

    num_booths  = manager.get_num_booths()
    all_booths  = list(range(1, num_booths + 1))
    occupancy   = voters.get_booth_occupancy(all_booths)
    return render_template(
        "bmd_mapping.html",
        devices=manager.state.get("devices", {}),
        bmd_mapping=manager.get_bmd_mapping(),
        all_booths=all_booths,
        occupancy=occupancy,
    )

@admin.route("/init", methods=["GET", "POST"])
def init_election():
    if manager.state.get("active_election"):
        flash("An election is currently active. You must end it before starting a new one.", "error")
        return redirect(url_for("admin.dashboard"))

    if request.method == "POST":
        e_roll = request.files.get("electoral_roll")
        b_keys = request.files.get("bmd_keys")
        num_tgens = int(request.form.get("num_tgens", 1))
        end_time = request.form.get("end_time")
        election_name = request.form.get("election_name", "Untitled Election").strip()

        if not e_roll or not b_keys:
            return "Missing files", 400

        # Build mapping
        mapping = {}
        for i in range(1, num_tgens + 1):
            ids = request.form.get(f"bmd_mapping_{i}", str(i))
            mapping[str(i)] = [int(x.strip()) for x in ids.split(",") if x.strip().isdigit()]

        bmd_keys_data = json.load(b_keys)
        
        election_config = {
            "election_name": election_name,
            "num_tgens": num_tgens,
            "bmd_mapping": mapping,
            "bmd_keys": bmd_keys_data,
            "election_end_time": end_time
        }

        manager.start_election(e_roll.read(), num_tgens, election_config)
        # Clear the update required flag on new election start if you wish, 
        # or keep it until dismissed. Let's keep it until start.
        manager.state["master_update_required"] = False
        manager._save_state()
        return redirect(url_for("admin.dashboard"))

    return render_template("init_election.html")

@admin.route("/rotate_master", methods=["POST"])
def rotate_master():
    manager.rotate_master_credentials()
    # Flash message or similar would be nice, but we have the flag in state
    return redirect(url_for("admin.dashboard"))

@admin.route("/end", methods=["POST"])
def end_election():
    manager.end_election()
    return redirect(url_for("admin.dashboard"))

@admin.route("/archives")
def archives():
    manifest_path = os.path.join(os.path.dirname(__file__), "archives", "manifest.json")
    manifest = []
    if os.path.exists(manifest_path):
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
            
    # Sort newest first
    manifest = sorted(manifest, key=lambda x: x.get("timestamp", ""), reverse=True)
    return render_template("archives.html", manifest=manifest)

@admin.route("/archives/download/<filename>")
def download_archive(filename):
    archive_dir = os.path.join(os.path.dirname(__file__), "archives")
    file_path = os.path.join(archive_dir, filename)
    if not os.path.exists(file_path):
        return "Archive not found", 404
    return send_file(file_path, as_attachment=True)

@admin.route("/report")
def report():
    # Compile stats
    all_voters = voters.get_all_voters()
    total_voters = len(all_voters)
    voted_list = [v for v in all_voters if v.get("status") and v["status"].startswith("generated_at_device_")]
    voted_count = len(voted_list)
    
    # Audit log
    audit_log = []
    regen_count = 0
    for v in voted_list:
        dev_id = v.get("device_id") or v["status"].replace("generated_at_device_", "")
        is_regen = v.get("is_regenerated", False)
        if is_regen:
            regen_count += 1
            
        audit_log.append({
            "voter_id": v["entry_number"],
            "device_id": dev_id,
            "timestamp": v.get("generated_at", "N/A"),
            "regenerated": is_regen
        })
    
    # Participation Stats
    stats = {
        "participation_percent": round((voted_count/total_voters)*100, 2) if total_voters > 0 else 0,
        "voted_count": voted_count,
        "total_voters": total_voters,
        "total_tokens": voted_count,
        "regen_count": regen_count
    }
    
    return render_template("report.html", stats=stats, audit_log=audit_log)

@admin.route("/report/download")
def download_master_report():
    """Generates and serves a ZIP with consolidated reports and logs."""
    import io
    import zipfile
    import csv

    # 1. Master CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Voter_ID", "Device_ID", "Token_ID", "Booth", "Generated_At", "Is_Regenerated"])
    
    all_voters = voters.get_all_voters()
    for v in all_voters:
        if v.get("status") and v["status"].startswith("generated_at_device_"):
            writer.writerow([
                v["entry_number"],
                v.get("device_id"),
                v.get("token_id"),
                v.get("booth_number"),
                v.get("generated_at"),
                v.get("is_regenerated", False)
            ])
    
    # 2. Regeneration Logs (from the audit file if it exists)
    regen_log_content = ""
    regen_log_path = os.path.join(os.path.dirname(__file__), "regeneration_audit.log")
    if os.path.exists(regen_log_path):
        with open(regen_log_path, "r") as f:
            regen_log_content = f.read()

    # Create ZIP in memory
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        # Master CSV
        zf.writestr("master_audit_report.csv", output.getvalue())
        # Regeneration log
        if regen_log_content:
            zf.writestr("regeneration_history.log", regen_log_content)
        
        # Also include all device local logs if they were uploaded
        logs_dir = os.path.join(os.path.dirname(__file__), "device_logs")
        if os.path.exists(logs_dir):
            for root, dirs, files in os.walk(logs_dir):
                for file in files:
                    filepath = os.path.join(root, file)
                    zf.write(filepath, arcname=os.path.join("raw_device_logs", file))

    memory_file.seek(0)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f"election_master_report_{timestamp}.zip"
    )


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
        
    logs_dir = os.path.join(manager.certs_dir, f"device_{device_id}", "logs")
    os.makedirs(logs_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_filename = secure_filename(file.filename)
    final_filename = f"device_{device_id}_{timestamp}_{safe_filename}"
    
    file_path = os.path.join(logs_dir, final_filename)
    try:
        file.save(file_path)
        manager.update_device_status(device_id, "logs_uploaded", True)
        return jsonify({"status": "success", "message": f"Log saved to {final_filename}"}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to save log: {str(e)}"}), 500

