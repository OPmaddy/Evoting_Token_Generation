#!/bin/bash
# setup_tls.sh
# Automates the generation of a private CA, server certificates, and client certificates

set -e

# Default values
SERVER_IP="192.168.1.100"
NUM_DEVICES=5
CERT_DIR="certs"

# Allow overriding via command line
if [ "$#" -ge 1 ]; then
    SERVER_IP=$1
fi
if [ "$#" -ge 2 ]; then
    NUM_DEVICES=$2
fi

echo "=========================================="
echo " EVoting TLS Certificate Generator script "
echo "=========================================="
echo "Server IP/Hostname: $SERVER_IP"
echo "Number of Devices:  $NUM_DEVICES"
echo "Output Directory:   ./$CERT_DIR"
echo "=========================================="

mkdir -p "$CERT_DIR"
cd "$CERT_DIR"

# --- 1. Generate CA ---
echo "=> Step 1: Generating Certificate Authority (CA)..."
if [ ! -f "ca.key" ]; then
    openssl genrsa -out ca.key 4096
    openssl req -new -x509 -days 3650 -key ca.key -out ca.crt \
        -subj "/C=IN/ST=Delhi/O=EVoting/CN=EVoting-CA"
    echo "   [OK] CA generated"
else
    echo "   [Skip] ca.key already exists, reusing existing CA"
fi

# --- 2. Generate Server Certificate ---
echo "=> Step 2: Generating Server Certificate..."
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr \
    -subj "/C=IN/ST=Delhi/O=EVoting/CN=evoting-server"

cat > server_ext.cnf << EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
IP.1 = $SERVER_IP
DNS.1 = evoting-server
DNS.2 = localhost
EOF

openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
    -CAcreateserial -out server.crt -days 825 \
    -extfile server_ext.cnf

rm server.csr
echo "   [OK] Server certificate generated"

# --- 3. Generate Client Certificates ---
echo "=> Step 3: Generating Client Certificates ($NUM_DEVICES devices)..."
cat > client_ext.cnf << EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature
extendedKeyUsage = clientAuth
EOF

for i in $(seq 1 $NUM_DEVICES); do
    DEVICE_NAME="device_${i}"
    openssl genrsa -out "${DEVICE_NAME}.key" 2048
    openssl req -new -key "${DEVICE_NAME}.key" -out "${DEVICE_NAME}.csr" \
        -subj "/C=IN/ST=Delhi/O=EVoting/CN=evoting-device-${i}"
    
    openssl x509 -req -in "${DEVICE_NAME}.csr" -CA ca.crt -CAkey ca.key \
        -CAcreateserial -out "${DEVICE_NAME}.crt" -days 825 \
        -extfile client_ext.cnf
        
    rm "${DEVICE_NAME}.csr"
    echo "   [OK] Generated $DEVICE_NAME"
done

# Cleanup temporary files
rm server_ext.cnf client_ext.cnf ca.srl 2>/dev/null || true

echo "=========================================="
echo "Done! All certificates generated in ./$CERT_DIR"
echo "Note: The server requires ca.crt, server.crt, and server.key"
echo "Each device 'N' requires ca.crt, device_N.crt, and device_N.key"
