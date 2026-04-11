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
ca_certs = TLS_CA_CERT
cert_reqs = ssl.CERT_REQUIRED
ssl_version = ssl.PROTOCOL_TLS_SERVER

def on_starting(server):
    """Ensure TLS certificates exist before starting the server."""
    if not os.path.isfile(TLS_SERVER_CERT):
        raise RuntimeError(f"Server certificate not found at {TLS_SERVER_CERT}")
    if not os.path.isfile(TLS_SERVER_KEY):
        raise RuntimeError(f"Server private key not found at {TLS_SERVER_KEY}")
    if not os.path.isfile(TLS_CA_CERT):
        raise RuntimeError(f"CA certificate not found at {TLS_CA_CERT}")
