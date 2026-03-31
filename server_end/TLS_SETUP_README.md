# TLS Certificate Setup Guide — EVoting Star Network

This guide explains how to generate and distribute TLS certificates for secure mutual authentication (mTLS) between the **central coordination server** and **N token generation devices** (Raspberry Pis).

## 🚀 Quick Start (Automated)

We have automated the entire generation and distribution process using two scripts located in the `server_end/` directory.

### 1. Generate All Certificates
Run the `setup_tls.sh` script on your workstation. This generates a private CA, a server certificate, and unique client certificates for $N$ devices.

```bash
# Usage: ./setup_tls.sh <SERVER_IP> <SERVER_HOSTNAME> <NUM_DEVICES>
./setup_tls.sh 192.168.1.100 evoting-server 5
```

**Output Structure (`all_certs/`):**
- `server_certs/certs/`: Contains `ca.crt`, `server.crt`, `server.key`.
- `device_N/certs/`: Contains `ca.crt`, `device_N.crt`, `device_N.key`, and `device_id.txt`.

### 2. Distribute to Devices
Automate the transfer of these certificates to your Raspberry Pis using `certs_transfer.sh`.

1. **Edit `device_ips.txt`**: Add the IP addresses of your Raspberry Pis (one per line).
2. **Run the transfer script**:
   ```bash
   ./certs_transfer.sh
   ```
   *Note: This script pings each device, handles SSH host verification automatically, and prompts for your SSH password just once for the whole batch.*

---

## 📂 Certificate Architecture

```
                    ┌─────────────────┐
                    │  Central Server  │
                    │  (server cert)   │
                    └───────┬─────────┘
                            │  TLS (mTLS)
            ┌───────────────┼───────────────┐
            │               │               │
    ┌───────▼──────┐ ┌──────▼───────┐ ┌─────▼────────┐
    │  Device 1    │ │  Device 2    │ │  Device N    │
    │ (client cert)│ │ (client cert)│ │ (client cert)│
    └──────────────┘ └──────────────┘ └──────────────┘
```

All certificates are signed by a **private Certificate Authority (CA)** generated during the setup.

---

## ⚙️ How Identity Works (Auto-Discovery)

The system is designed for "zero-config" deployment on the Raspberry Pis:

1. **`device_id.txt`**: When certificates are generated, a small text file containing the device's numeric ID (e.g., `1`) is placed in the `certs/` folder.
2. **Automatic Detection**: When `app.py` starts, it looks for `certs/device_id.txt`. If found, it automatically sets the `DEVICE_ID` and loads the corresponding certificates (`device_1.crt`, etc.).
3. **Seamless Deployment**: This means you can copy the **exact same code** to every Raspberry Pi. Their unique identity is determined solely by the certificate folder you transfer to them.

---

## 🛠️ Manual Generation (Reference)

If you prefer to run commands manually, here is the underlying logic used by the scripts.

### 1. Create the CA
```bash
openssl genrsa -out ca.key 4096
openssl req -new -x509 -days 3650 -key ca.key -out ca.crt \
    -subj "/C=IN/ST=Delhi/O=EVoting/CN=EVoting-CA"
```

### 2. Create Server Cert
```bash
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr -subj "/C=IN/ST=Delhi/O=EVoting/CN=evoting-server"

# Create SAN config (server_ext.cnf)
# subjectAltName = IP:192.168.1.100,DNS:evoting-server

openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 825 -extfile server_ext.cnf
```

### 3. Create Device Cert (N)
```bash
openssl genrsa -out device_N.key 2048
openssl req -new -key device_N.key -out device_N.csr -subj "/C=IN/ST=Delhi/O=EVoting/CN=evoting-device-N"

openssl x509 -req -in device_N.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out device_N.crt -days 825 -extfile client_ext.cnf
```

---

## 🔒 Security Notes

- **Protect `.key` files**: Never share them beyond the machine that uses them. The `ca.key` should ideally be stored offline on a secure machine after certificate generation, not on the server or any device.
- **SSH Automation**: The `certs_transfer.sh` script uses `sshpass`. Install it via `sudo apt install sshpass`.
- **Permissions**: The scripts automatically set tight permissions, but ensure your `certs/` folder on the Pi is not world-readable (`chmod 700 certs`).
- **Mutual TLS**: The server is configured to **strictly require** a valid client certificate signed by your CA. Connections from unauthorized devices will be rejected at the handshake level.
