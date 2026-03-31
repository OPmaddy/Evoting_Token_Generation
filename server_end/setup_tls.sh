#!/bin/bash
# setup_tls.sh
# Automates the generation of a private CA, server certificates, and client certificates

set -e

# Default values
SERVER_IP="192.168.1.100"
SERVER_NAME="evoting-server"
NUM_DEVICES=5
BASE_OUTPUT_DIR="all_certs"

# Allow overriding via command line
if [ "$#" -ge 1 ]; then
    SERVER_IP=$1
fi
if [ "$#" -ge 2 ]; then
    SERVER_NAME=$2
fi
if [ "$#" -ge 3 ]; then
    NUM_DEVICES=$3
fi

echo "=========================================="
echo " EVoting TLS Certificate Generator script "
echo "=========================================="
echo "Server IP:       $SERVER_IP"
echo "Server name:     $SERVER_NAME"
echo "Number of Devices:  $NUM_DEVICES"
echo "Output Directory:   ./$BASE_OUTPUT_DIR"
echo "=========================================="

mkdir -p "$BASE_OUTPUT_DIR"
# Work in a temporary directory for generation to avoid clutter
TEMP_DIR=$(mktemp -d)
cp -r . "$TEMP_DIR" # Copy scripts if needed (though not needed for openssl)
cd "$TEMP_DIR"

# --- 1. Generate CA ---
echo "=> Step 1: Generating Certificate Authority (CA)..."
openssl genrsa -out ca.key 4096
openssl req -new -x509 -days 3650 -key ca.key -out ca.crt \
    -subj "/C=IN/ST=Delhi/O=EVoting/CN=EVoting-CA"
echo "   [OK] CA generated"

# --- 2. Generate Server Certificate ---
echo "=> Step 2: Generating Server Certificate..."
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr \
    -subj "/C=IN/ST=Delhi/O=EVoting/CN=$SERVER_NAME"

cat > server_ext.cnf << EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
IP.1 = $SERVER_IP
DNS.1 = $SERVER_NAME
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

# --- 4. Organize Output ---
echo "=> Step 4: Organizing output into $BASE_OUTPUT_DIR..."
ORIGINAL_DIR=$OLDPWD # Mktemp CD'd us, get back the path to the project root

# Server Certs Folder
SERVER_DEST="$ORIGINAL_DIR/$BASE_OUTPUT_DIR/server_certs/certs"
mkdir -p "$SERVER_DEST"
cp ca.crt server.crt server.key "$SERVER_DEST/"

# Device Certs Folders
for i in $(seq 1 $NUM_DEVICES); do
    DEVICE_DEST="$ORIGINAL_DIR/$BASE_OUTPUT_DIR/device_${i}/certs"
    mkdir -p "$DEVICE_DEST"
    cp ca.crt "device_${i}.crt" "device_${i}.key" "$DEVICE_DEST/"
    echo "${i}" > "$DEVICE_DEST/device_id.txt"
done

# Cleanup temporary folder
cd "$ORIGINAL_DIR"
rm -rf "$TEMP_DIR"

echo "=========================================="
echo "Done! All certificates organized in ./$BASE_OUTPUT_DIR"
echo "Structure:"
echo "  $BASE_OUTPUT_DIR/server_certs/certs/   (For the Token Server)"
echo "  $BASE_OUTPUT_DIR/device_N/certs/      (Total $NUM_DEVICES devices)"
echo "=========================================="
