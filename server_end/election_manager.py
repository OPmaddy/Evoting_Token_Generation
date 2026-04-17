import os
import json
import datetime
import base64
import socket
import ipaddress
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives.asymmetric import rsa

STATE_FILE = "election_state.json"
CERTS_DIR = "all_certs"
MASTER_CERTS_DIR = "master_certs"

class ElectionManager:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.state_path = os.path.join(base_dir, STATE_FILE)
        self.certs_dir = os.path.join(base_dir, CERTS_DIR)
        self.master_dir = os.path.join(base_dir, MASTER_CERTS_DIR)
        self.state = self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_path):
            with open(self.state_path, "r") as f:
                return json.load(f)
        return {
            "active_election": False,
            "master_update_required": False,
            "config": {},
            "devices": {}
        }

    def _save_state(self):
        with open(self.state_path, "w") as f:
            json.dump(self.state, f, indent=4)

    def generate_ca(self, path, name):
        key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, u"IN"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"Delhi"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"EVoting"),
            x509.NameAttribute(NameOID.COMMON_NAME, name),
        ])
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.utcnow() - datetime.timedelta(days=1)
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=3650)
        ).add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True,
        ).add_extension(
            x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False, data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False),
            critical=True
        ).add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        ).sign(key, hashes.SHA256())


        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".key", "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ))
        with open(path + ".crt", "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        return key, cert

    def generate_cert(self, ca_key, ca_cert, cert_path, common_name, is_server=False):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, u"IN"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"Delhi"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"EVoting"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ])

        builder = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            ca_cert.subject
        ).public_key(
            key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.utcnow() - datetime.timedelta(days=1)
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=825)
        ).add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True
        ).add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        ).add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )

        if is_server:
            san_list = [x509.DNSName(common_name), x509.DNSName("localhost")]
            
            try:
                san_list.append(x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")))
                san_list.append(x509.IPAddress(ipaddress.IPv4Address("10.208.20.91"))) # Default
                
                # Fetch active local network IP
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
                san_list.append(x509.IPAddress(ipaddress.IPv4Address(local_ip)))
            except Exception:
                pass

            builder = builder.add_extension(
                x509.SubjectAlternativeName(san_list),
                critical=False,
            ).add_extension(
                x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=True, data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False),
                critical=True
            ).add_extension(
                x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
            )
        else:
            builder = builder.add_extension(
                x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False, data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False),
                critical=True
            ).add_extension(
                x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False
            )

        cert = builder.sign(ca_key, hashes.SHA256())


        os.makedirs(os.path.dirname(cert_path), exist_ok=True)
        with open(cert_path + ".key", "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ))
        with open(cert_path + ".crt", "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        return key, cert

    def setup_master_certs(self):
        """One-time setup for the Master CA, Master Client Cert, and Server Cert."""
        if os.path.exists(os.path.join(self.master_dir, "master_ca.crt")):
            # Upgrade path: ensure server.crt exists even if master CA is already there
            server_cert_path = os.path.join(self.master_dir, "server.crt")
            if not os.path.exists(server_cert_path):
                with open(os.path.join(self.master_dir, "master_ca.key"), "rb") as f:
                    ca_key = serialization.load_pem_private_key(f.read(), password=None)
                with open(os.path.join(self.master_dir, "master_ca.crt"), "rb") as f:
                    ca_cert = x509.load_pem_x509_certificate(f.read())
                self.generate_cert(ca_key, ca_cert, os.path.join(self.master_dir, "server"), u"evoting-server", is_server=True)
            
            self._update_ca_bundle()
            return
        
        self.rotate_master_credentials()

    def rotate_master_credentials(self):
        """Explicitly regenerate master CA, client certificate, and server certificate."""
        if os.path.exists(self.master_dir):
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            os.rename(self.master_dir, f"{self.master_dir}_old_{timestamp}")
            
        ca_key, ca_cert = self.generate_ca(os.path.join(self.master_dir, "master_ca"), u"EVoting-Master-CA")
        self.generate_cert(ca_key, ca_cert, os.path.join(self.master_dir, "master_client"), u"EVoting-Master-Client")
        self.generate_cert(ca_key, ca_cert, os.path.join(self.master_dir, "server"), u"evoting-server", is_server=True)
        
        self.state["master_update_required"] = True
        self._update_ca_bundle()
        self._save_state()
        print("Master credentials generated. Manual update required on stations.")

    def _update_ca_bundle(self):
        """Bundle all trusted CAs into one file for Gunicorn/mTLS."""
        bundle_path = os.path.join(self.base_dir, "ca_bundle.crt")
        cas = []
        
        # 1. Master CA
        m_ca = os.path.join(self.master_dir, "master_ca.crt")
        if os.path.exists(m_ca):
            with open(m_ca, "r") as f: cas.append(f.read())
            
        # 2. Election CA
        e_ca = os.path.join(self.certs_dir, "election_ca.crt")
        if os.path.exists(e_ca):
            with open(e_ca, "r") as f: cas.append(f.read())
            
        with open(bundle_path, "w") as f:
            f.write("\n".join(cas))
        return bundle_path

    def start_election(self, electoral_roll_content, num_tgens, election_config):
        # 1. Archive old election data if any
        if os.path.exists(self.certs_dir):
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            os.rename(self.certs_dir, f"{self.certs_dir}_{timestamp}")
        
        # NOTE: Master certificates are PERSISTENT and not rotated here.

        # 2. Generate Election CA and Certs (Stage 2)
        ca_key, ca_cert = self.generate_ca(os.path.join(self.certs_dir, "election_ca"), u"EVoting-Election-CA")
        
        # NOTE: The server ALWAYS identifies itself using the Master CA to simplify trust.
        with open(os.path.join(self.master_dir, "master_ca.crt"), "rb") as f:
            master_ca_bytes = f.read()

        # Device certs (Stage 2 - their identity)
        for i in range(1, num_tgens + 1):
            device_id = str(i)
            device_path = os.path.join(self.certs_dir, f"device_{device_id}", "certs")
            self.generate_cert(ca_key, ca_cert, os.path.join(device_path, f"device_{device_id}"), f"evoting-device-{device_id}")
            # The device uses the Master CA to verify the Server's identity
            with open(os.path.join(device_path, "ca.crt"), "wb") as f:
                f.write(master_ca_bytes)

        # 3. Update CA Bundle for mTLS trust
        self._update_ca_bundle()

        # 3b. Gracefully reload Gunicorn so it reads the new CA bundle into RAM
        try:
            import signal
            # Gunicorn arbiter is the parent of the worker process
            os.kill(os.getppid(), signal.SIGHUP)
        except Exception as e:
            print("Failed to send SIGHUP to Gunicorn:", e)


        # 4. Save state
        self.state["active_election"] = True
        self.state["master_update_required"] = self.state.get("master_update_required", False) 
        self.state["config"] = election_config
        self.state["devices"] = {str(i): {"provisioned": False, "last_active": None, "logs_uploaded": False} for i in range(1, num_tgens + 1)}
        self._save_state()

        # 5. Save Electoral Roll
        with open(os.path.join(self.base_dir, "..", "Electoral_Roll.csv"), "wb") as f:
            f.write(electoral_roll_content)

        return True

    def end_election(self):
        self.state["active_election"] = False
        self._save_state()
        return True

    def update_device_status(self, device_id, status_key, value):
        if device_id in self.state["devices"]:
            self.state["devices"][device_id][status_key] = value
            self.state["devices"][device_id]["last_active"] = datetime.datetime.now().isoformat()
            self._save_state()
