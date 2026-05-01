#!/usr/bin/env bash
set -euo pipefail
sudo apt update
sudo apt install -y python3 python3-venv ffmpeg git
sudo useradd -r -m -s /usr/sbin/nologin camera-uploader || true
sudo mkdir -p /opt/camera-uploader
sudo rsync -a --delete ./ /opt/camera-uploader/
sudo chown -R camera-uploader:camera-uploader /opt/camera-uploader
sudo -u camera-uploader python3 -m venv /opt/camera-uploader/venv
sudo -u camera-uploader /opt/camera-uploader/venv/bin/pip install --upgrade pip
sudo -u camera-uploader /opt/camera-uploader/venv/bin/pip install -r /opt/camera-uploader/requirements.txt
sudo install -m 644 /opt/camera-uploader/systemd/camera-uploader.service /etc/systemd/system/camera-uploader.service
sudo systemctl daemon-reload
sudo systemctl enable camera-uploader.service
sudo systemctl restart camera-uploader.service
echo "Installeret. Webinterface: http://<pi-ip>:8080"
