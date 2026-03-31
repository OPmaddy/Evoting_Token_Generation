#!/bin/bash
# certs_transfer.sh
# Automates the transfer of certificate folders to remote devices

set -e

# Configuration
BASE_DIR="all_certs"
IP_FILE="device_ips.txt"
TARGET_PATH="~/Evoting_Token_Generation/"

if [ ! -d "$BASE_DIR" ]; then
    echo "Error: $BASE_DIR directory not found. Run setup_tls.sh first."
    exit 1
fi

# Fetch IPs from command line arguments OR from the device_ips.txt file
DEVICE_IPS=("$@")
if [ ${#DEVICE_IPS[@]} -eq 0 ]; then
    if [ -f "$IP_FILE" ]; then
        echo "[Info] No IPs provided on command line. Reading from $IP_FILE..."
        # Read file into array, ignoring empty lines and comments
        readarray -t DEVICE_IPS < <(grep -v -E '^\s*(#|$)' "$IP_FILE")
    else
        echo "Usage: ./certs_transfer.sh <IP1> <IP2> ... <IPN>"
        echo "OR: Provide IP addresses in a file named '$IP_FILE' (one per line)."
        exit 1
    fi
fi

NUM_IPS=${#DEVICE_IPS[@]}
if [ "$NUM_IPS" -eq 0 ]; then
    echo "Error: No IP addresses found in $IP_FILE or command line."
    exit 1
fi

echo "=========================================="
echo " EVoting Certificate Distribution Tool    "
echo "=========================================="
echo "Target path on devices: $TARGET_PATH"
echo "Devices to process:     $NUM_IPS"
echo "=========================================="

# Prompt for credentials once
read -p "Enter SSH Username (e.g., pi): " SSH_USER
read -s -p "Enter SSH Password: " SSH_PASS
echo ""

# Check for sshpass
SSHPASS_CMD=""
if command -v sshpass >/dev/null 2>&1; then
    SSHPASS_CMD="sshpass -p $SSH_PASS"
    echo "[Info] sshpass found, automation enabled."
else
    echo "[Warning] sshpass not found. Manual password entry may be required."
fi

# Ensure known_hosts exists
touch ~/.ssh/known_hosts

for i in "${!DEVICE_IPS[@]}"; do
    DEVICE_ID=$((i + 1))
    IP=${DEVICE_IPS[$i]}
    DEVICE_FOLDER="$BASE_DIR/device_${DEVICE_ID}"
    
    echo "------------------------------------------"
    echo "Processing Device $DEVICE_ID at $IP..."
    
    if [ ! -d "$DEVICE_FOLDER" ]; then
        echo "[Error] Local folder $DEVICE_FOLDER not found. Skipping."
        continue
    fi
    
    # 1. Ping test
    if ping -c 1 -W 2 "$IP" >/dev/null 2>&1; then
        echo "[OK] Device $IP is reachable."
    else
        echo "[Error] Device $IP is unreachable. Skipping."
        continue
    fi
    
    # 2. Confirmation
    read -p "Transfer certificates to Device $DEVICE_ID ($IP)? (y/n): " CONFIRM
    if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
        echo "Skipping Device $DEVICE_ID."
        continue
    fi
    
    # 3. Handle SSH Key fingerprint (Auto-accept)
    echo "Updating SSH fingerprints for $IP..."
    # Remove old entry if exists to avoid conflicts
    ssh-keygen -R "$IP" >/dev/null 2>&1 
    ssh-keyscan -H "$IP" >> ~/.ssh/known_hosts 2>/dev/null
    
    # 4. Transfer folder
    echo "Transferring $DEVICE_FOLDER/certs to $IP:$TARGET_PATH..."
    if [ -n "$SSHPASS_CMD" ]; then
        # Use sshpass for automated password entry
        $SSHPASS_CMD scp -o StrictHostKeyChecking=no -r "$DEVICE_FOLDER/certs" "${SSH_USER}@${IP}:${TARGET_PATH}"
    else
        # Fallback to manual password entry
        scp -o StrictHostKeyChecking=no -r "$DEVICE_FOLDER/certs" "${SSH_USER}@${IP}:${TARGET_PATH}"
    fi
    
    if [ $? -eq 0 ]; then
        echo "[Success] Device $DEVICE_ID updated successfully."
    else
        echo "[Failed] Transfer to Device $DEVICE_ID failed."
    fi
done

echo "=========================================="
echo "Distribution Complete."
echo "=========================================="
