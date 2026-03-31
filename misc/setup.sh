#!/bin/bash

# Exit on error
set -e

echo "==================================================="
echo "  Raspberry Pi Setup Script for Token Generation   "
echo "==================================================="

echo "[1/4] Installing System Dependencies (Requires sudo)..."
sudo apt update
sudo apt install -y libgtk-3-dev libcanberra-gtk3-module pkg-config
sudo apt install -y libcap-dev
sudo apt install -y libcamera-apps python3-libcamera
sudo apt install -y python3-tk python3-pil python3-pil.imagetk
sudo apt install -y fonts-freefont-ttf

echo "[2/4] Setting up X11 for GUI (Required for OS Lite)..."
sudo apt install -y xserver-xorg xinit x11-xserver-utils matchbox-window-manager

echo "[3/4] Setting up Hardware & I2C..."
sudo apt install -y i2c-tools python3-smbus python3-pip

echo "Please ensure I2C is enabled in raspi-config!"
echo "If not enabled, run 'sudo raspi-config', navigate to Interface Options -> I2C -> Enable, and reboot."

echo "[4/4] Setting up Python Virtual Environment..."
# Create venv with system site packages to access libcamera and other system python libs
python -m venv venv --system-site-packages
source venv/bin/activate

echo "Installing Python Requirements..."
pip install --upgrade pip
pip install -r requirements.txt

echo "==================================================="
echo "  Setup Complete!                                  "
echo "==================================================="
echo "Note: The embedding model for FaceAnalysis is automatically installed"
echo "the first time the system runs."
echo ""
echo "To run the app from RPi OS Lite console:"
echo "  source venv/bin/activate"
echo "  startx ./venv/bin/python app.py"
echo "==================================================="
