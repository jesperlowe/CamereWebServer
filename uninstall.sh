#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME=CameraWebService
INSTALL_DIR=/opt/CameraWebService
SERVICE_USER=camerawebservice

echo "=== CameraWebService afinstallation ==="

sudo systemctl disable --now "$SERVICE_NAME.service" || true
sudo rm -f "/etc/systemd/system/$SERVICE_NAME.service"
sudo systemctl daemon-reload
sudo rm -rf "$INSTALL_DIR"
sudo userdel -r "$SERVICE_USER" || true

echo "Afinstalleret."
