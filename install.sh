#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR=/opt/CameraWebService
SERVICE_USER=camerawebservice
SERVICE_NAME=CameraWebService

echo "=== CameraWebService installer ==="

sudo apt update
sudo apt install -y python3 python3-venv ffmpeg git

# Opret systembruger hvis den ikke findes
sudo useradd -r -m -s /usr/sbin/nologin "$SERVICE_USER" || true

# Kopiér kode
sudo mkdir -p "$INSTALL_DIR"
sudo rsync -a --delete ./ "$INSTALL_DIR/"
sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"

# Opret venv og installér pakker
sudo -u "$SERVICE_USER" python3 -m venv "$INSTALL_DIR/venv"
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install --upgrade pip
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# Installér og aktivér systemd-service
sudo install -m 644 "$INSTALL_DIR/systemd/$SERVICE_NAME.service" "/etc/systemd/system/$SERVICE_NAME.service"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME.service"
sudo systemctl restart "$SERVICE_NAME.service"

echo ""
echo "=== Installeret ==="
echo "Webinterface: http://$(hostname -I | awk '{print $1}'):8080"
echo "Status:       sudo systemctl status $SERVICE_NAME"
echo "Logs:         sudo journalctl -u $SERVICE_NAME -f"
