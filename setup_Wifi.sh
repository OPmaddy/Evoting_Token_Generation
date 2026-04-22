#!/bin/bash

# ---------- AUTO SUDO ----------
if [ "$EUID" -ne 0 ]; then
  echo "Re-running with sudo..."
  exec sudo "$0" "$@"
fi

echo "==== WiFi Setup Script ===="

# -------- HOTSPOT (Primary) --------
read -p "Enter Hotspot SSID: " HOTSPOT_SSID
read -s -p "Enter Hotspot Password: " HOTSPOT_PASS
echo ""

# -------- WPA2 ENTERPRISE (Backup) --------
read -p "Enter Enterprise SSID (e.g. IITD_WIFI): " ENT_SSID
read -p "Enter Enterprise Username: " ENT_USER
read -s -p "Enter Enterprise Password: " ENT_PASS
echo ""

echo ""
echo "Configuring networks..."

# ---------- CLEAN OLD CONNECTIONS ----------
nmcli connection delete "$HOTSPOT_SSID" 2>/dev/null
nmcli connection delete "$ENT_SSID" 2>/dev/null

# ---------- HOTSPOT SETUP ----------
echo "Setting up hotspot (Primary)..."

nmcli connection add type wifi ifname wlan0 con-name "$HOTSPOT_SSID" ssid "$HOTSPOT_SSID"

nmcli connection modify "$HOTSPOT_SSID" wifi-sec.key-mgmt wpa-psk
nmcli connection modify "$HOTSPOT_SSID" wifi-sec.psk "$HOTSPOT_PASS"
nmcli connection modify "$HOTSPOT_SSID" connection.autoconnect yes
nmcli connection modify "$HOTSPOT_SSID" connection.autoconnect-priority 10

# ---------- ENTERPRISE WIFI SETUP ----------
echo "Setting up enterprise WiFi (Backup)..."

nmcli connection add type wifi ifname wlan0 con-name "$ENT_SSID" ssid "$ENT_SSID" \
  wifi-sec.key-mgmt wpa-eap \
  802-1x.eap peap \
  802-1x.identity "$ENT_USER" \
  802-1x.password "$ENT_PASS" \
  802-1x.phase2-auth mschapv2 \
  802-1x.system-ca-certs yes \
  connection.autoconnect yes \
  connection.autoconnect-priority 5

# ---------- CONNECT PRIMARY ----------
echo "Connecting to primary network..."
nmcli connection up "$HOTSPOT_SSID"

sleep 3

# ---------- STATUS ----------
echo ""
echo "==== CURRENT CONNECTION STATUS ===="
nmcli -t -f ACTIVE,SSID,SIGNAL dev wifi | grep '^yes'

echo ""
echo "==== SAVED CONNECTIONS ===="
nmcli connection show

echo ""
echo "==== DONE ===="