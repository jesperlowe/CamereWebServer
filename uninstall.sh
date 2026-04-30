#!/usr/bin/env bash
set -euo pipefail
sudo systemctl disable --now camera-uploader.service || true
sudo rm -f /etc/systemd/system/camera-uploader.service
sudo systemctl daemon-reload
sudo rm -rf /opt/camera-uploader
sudo userdel -r camera-uploader || true
echo "Afinstalleret"
