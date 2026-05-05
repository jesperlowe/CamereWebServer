# Camera Uploader til Raspberry Pi 4

Webbaseret løsning der henter snapshots fra RTSP/RTSPS med `ffmpeg` og uploader direkte fra RAM (ingen permanent lokal JPG).

## Hardwarekrav
- Raspberry Pi 4
- SD-kort (16GB+)
- Netværk (Ethernet DHCP som standard)

## SD-kort klargøring
1. Brug Raspberry Pi Imager med **Raspberry Pi OS Lite**.
2. Aktivér SSH i Imager advanced options.
3. Boot Pi og find IP:
   - `hostname -I`
   - eller i router DHCP leases

Webinterface: `http://<pi-ip>:8080`

## Installation
```bash
git clone <repo-url>
cd CameraWebService
./install.sh
```

## Brug
- Login: `admin/admin` (du bliver tvunget til at skifte password)
- Konfigurer kamera, interval og uploadmetode.
- Brug “Test kamera” og “Upload testbillede”.

## UniFi Protect RTSPS
Brug Protect stream-URL i feltet RTSP URL (fx `rtsps://...`).

## SFTP opsætning
Udfyld host, port, user, password eller private key path, og remote path.

## WordPress plugin
Zip mappen `wordpress-plugin/camera-snapshot` og installer i WordPress.
REST endpoint: `/wp-json/camera-snapshot/v1/upload`
Shortcode: `[camera_snapshot]`

## Fejlfinding
- Se logs: web UI `/logs` eller `journalctl -u camera-uploader -n 100`
- Tjek service: `systemctl status camera-uploader`

## Sikkerhed
- Secrets gemmes lokalt i `/opt/camera-uploader/config.json` med `chmod 600`
- Passwords/tokens vises ikke efter gem
