# TLS Certificate Setup Guide — EVoting Star Network

This guide explains how to generate and distribute TLS certificates for secure mutual authentication (mTLS) between the **central coordination server** and **N token generation devices** (Raspberry Pis).

## Architecture

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

All certificates are signed by the **same private Certificate Authority (CA)**. The CA cert is distributed to both server and clients so each side can verify the other.

---

## Prerequisites

- **OpenSSL** installed on the machine generating certificates (any Linux/Mac/WSL will work)
  ```bash
  openssl version   # should print OpenSSL 1.1.1+ or 3.x
  ```

---

## Step 1: Create the Certificate Authority (CA)

This CA is your own private root of trust. Run these commands **once** on a secure machine.

```bash
# Create a directory for all cert material
mkdir -p certs && cd certs

# 1a. Generate CA private key (keep this SECRET)
openssl genrsa -out ca.key 4096

# 1b. Generate CA certificate (valid for 10 years)
openssl req -new -x509 -days 3650 -key ca.key -out ca.crt \
    -subj "/C=IN/ST=Delhi/O=EVoting/CN=EVoting-CA"
```

**Output files:**
| File     | Purpose                                    | Keep Secret? |
|----------|--------------------------------------------|:------------:|
| `ca.key` | CA private key — signs all other certs     | ✅ YES        |
| `ca.crt` | CA certificate — distributed to everyone   | ❌ No         |

---

## Step 2: Generate the Server Certificate

Run on the machine that generates certs (not necessarily the server itself).

```bash
# 2a. Generate server private key
openssl genrsa -out server.key 2048

# 2b. Create a Certificate Signing Request (CSR)
#     Replace <SERVER_IP> with your server's actual IP address or hostname.
openssl req -new -key server.key -out server.csr \
    -subj "/C=IN/ST=Delhi/O=EVoting/CN=evoting-server"

# 2c. Create a SAN (Subject Alternative Name) config
#     This is CRITICAL — TLS clients verify the server's IP/hostname against SANs.
cat > server_ext.cnf << EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
IP.1 = 192.168.1.100
DNS.1 = evoting-server
DNS.2 = localhost
EOF

# ⚠️  IMPORTANT: Edit server_ext.cnf and replace 192.168.1.100 with your
#     actual server IP. Add more IP.X or DNS.X entries if needed.

# 2d. Sign the server certificate with the CA
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
    -CAcreateserial -out server.crt -days 825 \
    -extfile server_ext.cnf
```

**Output files:**
| File         | Deploy To       | Keep Secret? |
|--------------|-----------------|:------------:|
| `server.key` | Server only     | ✅ YES        |
| `server.crt` | Server only     | ❌ No         |
| `server.csr` | Can be deleted  | —            |

---

## Step 3: Generate Client Certificates (One Per Device)

Repeat these commands for **each** Raspberry Pi device (device 1, 2, 3, ... N).

```bash
# Replace <DEVICE_NUM> with 1, 2, 3, etc.
DEVICE_NUM=1

# 3a. Generate client private key
openssl genrsa -out "device_${DEVICE_NUM}.key" 2048

# 3b. Create CSR
openssl req -new -key "device_${DEVICE_NUM}.key" -out "device_${DEVICE_NUM}.csr" \
    -subj "/C=IN/ST=Delhi/O=EVoting/CN=evoting-device-${DEVICE_NUM}"

# 3c. Create client extension config
cat > client_ext.cnf << EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature
extendedKeyUsage = clientAuth
EOF

# 3d. Sign with the CA
openssl x509 -req -in "device_${DEVICE_NUM}.csr" -CA ca.crt -CAkey ca.key \
    -CAcreateserial -out "device_${DEVICE_NUM}.crt" -days 825 \
    -extfile client_ext.cnf

echo "Generated cert for device ${DEVICE_NUM}"
```

### Batch Generation Script

For convenience, to generate certs for devices 1 through N:

```bash
#!/bin/bash
# generate_device_certs.sh <NUM_DEVICES>

NUM=${1:-5}

for i in $(seq 1 $NUM); do
    openssl genrsa -out "device_${i}.key" 2048
    openssl req -new -key "device_${i}.key" -out "device_${i}.csr" \
        -subj "/C=IN/ST=Delhi/O=EVoting/CN=evoting-device-${i}"
    openssl x509 -req -in "device_${i}.csr" -CA ca.crt -CAkey ca.key \
        -CAcreateserial -out "device_${i}.crt" -days 825 \
        -extfile client_ext.cnf
    rm "device_${i}.csr"
    echo "✓ Device $i certificate generated"
done
```

---

## Step 4: Distribute Certificates

### On the Central Server

Place these files in `server_end/certs/`:

```
server_end/
└── certs/
    ├── ca.crt          ← CA certificate (to verify client certs)
    ├── server.crt      ← Server's own certificate
    └── server.key      ← Server's private key (PROTECT THIS)
```

### On Each Raspberry Pi Device

Copy the following files to each device (e.g., via `scp`):

```bash
# From the cert generation machine:
scp ca.crt device_1.crt device_1.key pi@<DEVICE_1_IP>:~/evoting/certs/
scp ca.crt device_2.crt device_2.key pi@<DEVICE_2_IP>:~/evoting/certs/
# etc.
```

Each device should have:
```
~/evoting/certs/
├── ca.crt          ← CA certificate (to verify server cert)
├── device_X.crt    ← This device's certificate
└── device_X.key    ← This device's private key (PROTECT THIS)
```

---

## Step 5: Connecting from a Client Device (Python Example)

Each Raspberry Pi uses its client certificate when making API calls:

```python
import requests

SERVER_URL = "https://192.168.1.100:5000"
CERT = ("certs/device_1.crt", "certs/device_1.key")
CA_BUNDLE = "certs/ca.crt"

# Example: check voter status
response = requests.get(
    f"{SERVER_URL}/api/voter/2022EE11737",
    cert=CERT,
    verify=CA_BUNDLE,
)
print(response.json())
```

Or with `curl`:
```bash
curl --cert certs/device_1.crt \
     --key certs/device_1.key \
     --cacert certs/ca.crt \
     https://192.168.1.100:5000/api/health
```

---

## Step 6: Certificate Renewal

Certificates have an expiry (825 days as configured above). To renew:

1. **Keep the same CA key and cert** (unless compromised)
2. Regenerate the server/device certs using the same commands in Steps 2–3
3. Redistribute the new `.crt` and `.key` files
4. Restart the server and client applications

### If the CA is Compromised

1. Generate a **new CA** (Step 1)
2. Re-sign **all** server and client certificates with the new CA
3. Replace `ca.crt` on **every** machine

---

## Security Notes

- **Never share `.key` files** beyond the machine that uses them.
- **`ca.key`** should be stored offline on a secure machine after certificate generation, not on the server or any device.
- File permissions on `.key` files should be `600` (owner read-only):
  ```bash
  chmod 600 *.key
  ```
- The server enforces `ssl.CERT_REQUIRED`, so any device without a valid client certificate signed by the CA will be **rejected**.
- TLS 1.2 is the minimum version; TLS 1.0 and 1.1 are explicitly blocked.
