#!/bin/bash

# Exit on error
set -e

echo "==================================================="
echo "  Raspberry Pi Setup Script for Token Generation   "
echo "==================================================="

echo "[1/4] Installing System Dependencies (Requires sudo)..."
sudo apt update
sudo apt install -y libgtk2.0-dev pkg-config
sudo apt install -y libcap-dev
sudo apt install -y libcamera-apps python3-libcamera
sudo apt install -y python3-tk
sudo apt install -y python3-pil python3-pil.imagetk python3-tk

echo "[2/4] Setting up I2C for RFID Reader..."
sudo apt install -y i2c-tools python3-smbus python3-pip

echo "Please ensure I2C is enabled in raspi-config!"
echo "If not enabled, run 'sudo raspi-config', navigate to Interface Options -> I2C -> Enable, and reboot."

echo "[3/4] Creating Python Virtual Environment..."
# Create venv with system site packages to access libcamera and other system python libs
python -m venv venv --system-site-packages

echo "[4/4] Installing Python Requirements in Virtual Environment..."
source venv/bin/activate
pip install -r requirements.txt

echo "==================================================="
echo "  Setup Complete!                                  "
echo "==================================================="
echo "Note: The embedding model for FaceAnalysis is automatically installed"
echo "the first time the system runs."
echo ""
echo "To activate the environment and run the app:"
echo "  source venv/bin/activate"
echo "  python app.py"
echo "==================================================="
