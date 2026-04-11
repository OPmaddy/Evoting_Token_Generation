"""
Central Server Configuration for Multi-Device Token Generation.
All paths and settings can be overridden via environment variables.
"""
import os

# ─── MongoDB ───────────────────────────────────────────────────────────────────
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "evoting")
MONGO_COLLECTION = os.environ.get("MONGO_COLLECTION", "voters")

# ─── Server ───────────────────────────────────────────────────────────────────
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "5000"))

# ─── TLS / mTLS ──────────────────────────────────────────────────────────────
# Paths are relative to the server_end/ directory unless absolute.
TLS_CERT_DIR = os.environ.get("TLS_CERT_DIR", os.path.join(os.path.dirname(__file__), "certs"))

TLS_SERVER_CERT = os.environ.get("TLS_SERVER_CERT", os.path.join(TLS_CERT_DIR, "server.crt"))
TLS_SERVER_KEY  = os.environ.get("TLS_SERVER_KEY",  os.path.join(TLS_CERT_DIR, "server.key"))
TLS_CA_CERT     = os.environ.get("TLS_CA_CERT",     os.path.join(TLS_CERT_DIR, "ca.crt"))

# ─── Stale Request Timeout ────────────────────────────────────────────────────
# If a device requests a token but never confirms/cancels, the request is
# considered stale after this many seconds and automatically reverted to
# "not_generated" on the next query.
STALE_REQUEST_TIMEOUT_SECONDS = int(os.environ.get("STALE_REQUEST_TIMEOUT", "60"))  # 1 minute

# ─── Electoral Roll CSV ──────────────────────────────────────────────────────
ELECTORAL_ROLL_CSV = os.environ.get(
    "ELECTORAL_ROLL_CSV",
    os.path.join(os.path.dirname(__file__), "..", "Electoral_Roll.csv")
)
