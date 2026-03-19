"""
Central Token Generation Coordination Server.

Usage:
    python app.py              # Start with TLS (production)
    python app.py --no-tls     # Start without TLS (local development)
"""

import argparse
import ssl
import sys
import os

from flask import Flask
from routes import api
from config import (
    SERVER_HOST,
    SERVER_PORT,
    TLS_SERVER_CERT,
    TLS_SERVER_KEY,
    TLS_CA_CERT,
)


def create_app() -> Flask:
    """Flask application factory."""
    application = Flask(__name__)
    application.register_blueprint(api)
    return application


def build_tls_context() -> ssl.SSLContext:
    """
    Build an SSLContext that enforces mutual TLS:
      - Server presents its own certificate
      - Server requires the client to present a certificate signed by the CA
    """
    if not os.path.isfile(TLS_SERVER_CERT):
        print(f"ERROR: Server certificate not found at {TLS_SERVER_CERT}")
        print("       Run the TLS setup procedure described in TLS_SETUP_README.md")
        sys.exit(1)

    if not os.path.isfile(TLS_SERVER_KEY):
        print(f"ERROR: Server private key not found at {TLS_SERVER_KEY}")
        sys.exit(1)

    if not os.path.isfile(TLS_CA_CERT):
        print(f"ERROR: CA certificate not found at {TLS_CA_CERT}")
        sys.exit(1)

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=TLS_SERVER_CERT, keyfile=TLS_SERVER_KEY)
    ctx.load_verify_locations(cafile=TLS_CA_CERT)

    # Require the client to present a valid certificate signed by our CA
    ctx.verify_mode = ssl.CERT_REQUIRED

    # Minimum TLS 1.2 — reject older, insecure protocols
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    return ctx


def main():
    parser = argparse.ArgumentParser(description="EVoting Token Coordination Server")
    parser.add_argument(
        "--no-tls",
        action="store_true",
        help="Disable TLS (for local development/testing only)",
    )
    parser.add_argument(
        "--host",
        default=SERVER_HOST,
        help=f"Host to bind to (default: {SERVER_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=SERVER_PORT,
        help=f"Port to bind to (default: {SERVER_PORT})",
    )
    args = parser.parse_args()

    application = create_app()

    if args.no_tls:
        print("=" * 60)
        print("  WARNING: Running WITHOUT TLS — development mode only!")
        print("=" * 60)
        application.run(host=args.host, port=args.port, debug=True)
    else:
        context = build_tls_context()
        print("=" * 60)
        print("  Starting server with mutual TLS (mTLS)")
        print(f"  Cert : {TLS_SERVER_CERT}")
        print(f"  Key  : {TLS_SERVER_KEY}")
        print(f"  CA   : {TLS_CA_CERT}")
        print("=" * 60)
        application.run(
            host=args.host,
            port=args.port,
            ssl_context=context,
            debug=False,
        )


if __name__ == "__main__":
    main()
