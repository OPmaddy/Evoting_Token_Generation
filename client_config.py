"""
Client configuration for connecting to the central Token Coordination Server.
All settings can be overridden via environment variables.
"""
import os
import json

# ─── Server Connection ────────────────────────────────────────────────────────
# Load server config from external JSON if available (priority)
SERVER_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "server_config.json")
_url_from_file = None
if os.path.isfile(SERVER_CONFIG_PATH):
    try:
        with open(SERVER_CONFIG_PATH, "r") as f:
            _url_from_file = json.load(f).get("server_url")
    except Exception:
        pass

# Base URL of the central coordination server
SERVER_URL = _url_from_file or os.environ.get("SERVER_URL", "https://10.208.20.91:5000")

# ─── TLS Client Certificates ─────────────────────────────────────────────────
# Directory containing TLS certs for this device
TLS_CERT_DIR = os.environ.get("TLS_CERT_DIR", os.path.join(os.path.dirname(__file__), "certs"))

# ─── Device Identity ──────────────────────────────────────────────────────────
# Try to find device ID in the root folder, or alternatively the certs folder
_device_id_path = os.path.join(os.path.dirname(__file__), "device_id.txt")
if not os.path.isfile(_device_id_path):
    _device_id_path = os.path.join(TLS_CERT_DIR, "device_id.txt")
_id_from_file = None
if os.path.isfile(_device_id_path):
    try:
        with open(_device_id_path, "r") as f:
            _id_from_file = f.read().strip()
    except Exception:
        pass

# Unique numeric ID for this token generation device (e.g. "1", "2", "3")
DEVICE_ID = _id_from_file or os.environ.get("DEVICE_ID", "1")

# Client certificate + key (unique per device)
CLIENT_CERT = os.environ.get("CLIENT_CERT", os.path.join(TLS_CERT_DIR, f"device_{DEVICE_ID}.crt"))
CLIENT_KEY  = os.environ.get("CLIENT_KEY",  os.path.join(TLS_CERT_DIR, f"device_{DEVICE_ID}.key"))

# CA certificate (shared — same CA that signed the server cert)
CA_CERT = os.environ.get("CA_CERT", os.path.join(TLS_CERT_DIR, "ca.crt"))

# ─── Master Certificates (One-time manual placement) ─────────────────────────
MASTER_CERT_DIR = os.path.join(TLS_CERT_DIR, "master")
MASTER_CERT = os.path.join(MASTER_CERT_DIR, "master_client.crt")
MASTER_KEY  = os.path.join(MASTER_CERT_DIR, "master_client.key")
MASTER_CA   = os.path.join(MASTER_CERT_DIR, "master_ca.crt")

# ─── Development / Offline Mode ──────────────────────────────────────────────
# Set to True to disable TLS verification (development only!)
DISABLE_TLS = os.environ.get("DISABLE_TLS", "false").lower() in ("true", "1", "yes")
