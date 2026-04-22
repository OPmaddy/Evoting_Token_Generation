import os
import json
import datetime
import base64
import socket
import ipaddress
import zipfile
import shutil
import glob
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives.asymmetric import rsa
from pymongo import MongoClient

import db_init
from models import VoterCollection
from config import MONGO_URI, MONGO_DB_NAME

STATE_FILE = "election_state.json"
CERTS_DIR = "all_certs"
MASTER_CERTS_DIR = "master_certs"

class ElectionManager:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.certs_dir = os.path.join(base_dir, CERTS_DIR)
        self.master_dir = os.path.join(base_dir, MASTER_CERTS_DIR)
        
        # Initialize MongoDB connection for shared state
        self.client = MongoClient(MONGO_URI)
        self.db = self.client[MONGO_DB_NAME]
        self.settings = self.db["election_settings"]

    @property
    def state(self):
        """Fetch the latest state from MongoDB (shared across Gunicorn workers)."""
        doc = self.settings.find_one({"type": "main_state"})
        if not doc:
            return {
                "active_election": False,
                "master_update_required": False,
                "config": {},
                "devices": {}
            }
        return doc

    def _save_state(self, new_state):
        """Persist state to MongoDB."""
        # Ensure _id is not in the set payload to avoid immutable field errors
        new_state.pop("_id", None)
        self.settings.update_one(
            {"type": "main_state"},
            {"$set": new_state},
            upsert=True
        )

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
            # Join with triple newlines to ensure clean separation even if inputs lack them
            f.write("\n\n".join([c.strip() for c in cas if c.strip()]))
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


        # Ensure BMD Keys contain the shared AES key
        if "aes_key" not in election_config.get("bmd_keys", {}):
            print("Warning: aes_key not found in bmd_keys. Using default key.")
            if "bmd_keys" not in election_config:
                election_config["bmd_keys"] = {}
            election_config["bmd_keys"]["aes_key"] = "632af6d3184f4f3460e42d76587c6722d56a7c9360824699564f89d0f4d36ef5"

        # 4. Save state
        new_state = self.state
        new_state["active_election"] = True
        new_state["active_election_name"] = election_config.get("election_name", "Untitled")
        new_state["master_update_required"] = False  # Reset on new election
        new_state["config"] = election_config
        new_state["devices"] = {str(i): {"provisioned": False, "last_active": None, "logs_uploaded": False} for i in range(1, num_tgens + 1)}
        self._save_state(new_state)

        # 5. Save Electoral Roll
        csv_path = os.path.join(self.base_dir, "..", "Electoral_Roll.csv")
        with open(csv_path, "wb") as f:
            f.write(electoral_roll_content)

        # 6. Wipe and Reset Database securely
        db_init.import_electoral_roll(csv_path, drop_existing=True)

        return True

    def end_election(self):
        # Package Archive before clearing
        election_name = self.state.get("config", {}).get("election_name", "Untitled")
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join([c for c in election_name if c.isalpha() or c.isdigit() or c==' ']).rstrip().replace(" ", "_")
        archive_dir = os.path.join(self.base_dir, "archives")
        os.makedirs(archive_dir, exist_ok=True)
        
        archive_base = os.path.join(archive_dir, f"election_{safe_name}_{timestamp}")
        
        # Pull Voter Report from DB
        voters_db = VoterCollection()
        all_voters = list(voters_db.collection.find({}, {"_id": 0}))
        report_path = archive_base + "_report.json"
        with open(report_path, "w") as f:
            json.dump(all_voters, f, indent=4)
            
        # Create ZIP Archive containing the report and all device logs
        zip_path = archive_base + "_master.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(report_path, arcname="voter_report.json")
            
            # Archive Regeneration Audit Log if it exists
            audit_log_path = os.path.join(self.base_dir, "regeneration_audit.log")
            if os.path.exists(audit_log_path):
                zf.write(audit_log_path, arcname="regeneration_audit.log")
                # Once archived safely, we can delete the active one to start fresh for the next election
                os.remove(audit_log_path)
            
            # Find all uploaded logs (which could be .zip or .log based on extraction state)
            for file_ext in ["*.log", "*.zip"]:
                for log_file in glob.glob(os.path.join(self.certs_dir, "device_*", "logs", file_ext)):
                    parts = log_file.split(os.sep)
                    if len(parts) >= 3:
                        device_id = parts[-3]
                        filename = parts[-1]
                        zf.write(log_file, arcname=f"logs/{device_id}/{filename}")
                    
        # Add to manifest
        manifest_path = os.path.join(archive_dir, "manifest.json")
        manifest = []
        if os.path.exists(manifest_path):
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
        manifest.append({
            "name": election_name,
            "timestamp": timestamp,
            "zip": os.path.basename(zip_path)
        })
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=4)
        
        new_state = self.state
        new_state["active_election"] = False
        self._save_state(new_state)

        # Clear voters after archiving to refresh lifetime stats for next election
        voters_db.collection.delete_many({})
        
        return True

    def update_device_status(self, device_id, status_key, value):
        current = self.state
        if device_id in current.get("devices", {}):
            current["devices"][device_id][status_key] = value
            current["devices"][device_id]["last_active"] = datetime.datetime.now().isoformat()
            self._save_state(current)

    def get_bmd_mapping(self) -> dict:
        """Return the current device → allowed-booths mapping."""
        return self.state.get("config", {}).get("bmd_mapping", {})

    def update_bmd_mapping(self, device_id: str, booth_list: list) -> bool:
        """
        Overwrite the allowed booths for a single device and persist immediately.
        Returns True on success.
        """
        current = self.state
        if "config" not in current:
            current["config"] = {}
        if "bmd_mapping" not in current["config"]:
            current["config"]["bmd_mapping"] = {}
        current["config"]["bmd_mapping"][device_id] = booth_list
        self._save_state(current)
        return True

    def get_num_booths(self) -> int:
        """Return total number of BMDs configured in bmd_keys."""
        return self.state.get("config", {}).get("bmd_keys", {}).get("num_booths", 1)
