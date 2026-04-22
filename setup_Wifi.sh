#!/bin/bash

echo "==== WiFi Setup Script ===="

# -------- HOTSPOT (Primary) --------
read -p "Enter Hotspot SSID: " HOTSPOT_SSID
read -s -p "Enter Hotspot Password: " HOTSPOT_PASS
echo ""

# -------- WPA2 ENTERPRISE (Backup) --------
read -p "Enter Enterprise SSID (e.g. IITD_WiFi): " ENT_SSID
read -p "Enter Enterprise Username: " ENT_USER
read -s -p "Enter Enterprise Password: " ENT_PASS
echo ""

echo "Configuring networks..."

# Add hotspot (Primary)
nmcli connection add type wifi ifname wlan0 con-name "$HOTSPOT_SSID" ssid "$HOTSPOT_SSID"
nmcli connection modify "$HOTSPOT_SSID" wifi-sec.key-mgmt wpa-psk
nmcli connection modify "$HOTSPOT_SSID" wifi-sec.psk "$HOTSPOT_PASS"
nmcli connection modify "$HOTSPOT_SSID" connection.autoconnect yes
nmcli connection modify "$HOTSPOT_SSID" connection.autoconnect-priority 10

# Add WPA2 Enterprise (Backup)
nmcli connection add type wifi ifname wlan0 con-name "$ENT_SSID" ssid "$ENT_SSID"

nmcli connection modify "$ENT_SSID" wifi-sec.key-mgmt wpa-eap
nmcli connection modify "$ENT_SSID" 802-1x.eap peap
nmcli connection modify "$ENT_SSID" 802-1x.identity "$ENT_USER"
nmcli connection modify "$ENT_SSID" 802-1x.password "$ENT_PASS"
nmcli connection modify "$ENT_SSID" 802-1x.phase2-auth mschapv2

nmcli connection modify "$ENT_SSID" connection.autoconnect yes
nmcli connection modify "$ENT_SSID" connection.autoconnect-priority 5

# Bring up hotspot first
nmcli connection up "$HOTSPOT_SSID"

echo ""
echo "==== CURRENT CONNECTION STATUS ===="
nmcli -t -f ACTIVE,SSID,SIGNAL dev wifi | grep '^yes'

echo ""
echo "==== SAVED CONNECTIONS ===="
nmcli connection show
