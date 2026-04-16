import os
import multiprocessing
import ssl
from config import SERVER_HOST, SERVER_PORT, TLS_SERVER_CERT, TLS_SERVER_KEY, TLS_CA_CERT

bind = f"{SERVER_HOST}:{SERVER_PORT}"

# Utilize threads to gracefully handle multiple API calls concurrently
worker_class = "gthread"
workers = 1  # Number of worker processes (can be increased based on cores)
threads = 4  # Number of threads per worker

timeout = 120  # Prevent silent drops of long-running requests

# TLS Setup for mutual TLS (mTLS)
certfile = TLS_SERVER_CERT
keyfile = TLS_SERVER_KEY

# Use the managed CA bundle that includes both Master and Election CAs
ca_certs = os.path.join(os.path.dirname(__file__), "ca_bundle.crt")

cert_reqs = ssl.CERT_REQUIRED
ssl_version = ssl.PROTOCOL_TLS_SERVER

def on_starting(server):
    """Ensure TLS certificates and bundle exist before starting the server."""
    if not os.path.isfile(TLS_SERVER_CERT):
        raise RuntimeError(f"Server certificate not found at {TLS_SERVER_CERT}")
    if not os.path.isfile(TLS_SERVER_KEY):
        raise RuntimeError(f"Server private key not found at {TLS_SERVER_KEY}")
    
    bundle_path = os.path.join(os.path.dirname(__file__), "ca_bundle.crt")
    if not os.path.isfile(bundle_path):
        # Create a basic bundle if it doesn't exist yet (from main CA)
        with open(TLS_CA_CERT, "r") as f: main_ca = f.read()
        with open(bundle_path, "w") as f: f.write(main_ca)
