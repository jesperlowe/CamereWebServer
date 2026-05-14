# CameraWebService

**Version 3.1** — Webbaseret kameraservice til Raspberry Pi.

Henter snapshots fra RTSP/RTSPS-streams med `ffmpeg` og uploader direkte fra RAM (ingen permanent lokal JPG-fil). Integrerer med Track Status Light Server via en offentlig kamera-URL.

## Hardwarekrav

- Raspberry Pi 4 (eller nyere)
- SD-kort 16 GB+
- Netværk (Ethernet anbefales)

## Klargøring af SD-kort

1. Brug [Raspberry Pi Imager](https://www.raspberrypi.com/software/) med **Raspberry Pi OS Lite (64-bit)**.
2. Aktivér SSH og angiv hostname/bruger under *Advanced options* i Imager.
3. Boot Pi og find IP-adressen:
   ```bash
   hostname -I
   ```
   eller tjek DHCP-listen i din router.

## Installation

```bash
git clone https://github.com/jesperlowe/CameraWebService.git
cd CameraWebService
sudo bash install.sh
```

`install.sh` opretter systembrugeren `camerawebservice`, installerer til `/opt/CameraWebService`, bygger et Python venv og starter tjenesten automatisk.

Webinterface åbnes på: `http://<pi-ip>:8080`

## Opdatering til ny version

```bash
cd ~/CameraWebService
git pull
sudo bash install.sh
```

## Første login

- Brugernavn: `admin`
- Adgangskode: `admin`

Du tvinges til at vælge en ny adgangskode ved første login.

## Brug

| Fane | Formål |
|------|--------|
| **Dashboard** | Kamerastatus, seneste upload og fejl |
| **Kameraer** | Tilføj/ret kameraer — RTSP-URL, filnavn, optagelsesinterval |
| **Upload** | FTP/SFTP/WordPress upload-konfiguration og offentlig URL |
| **Tidsplan** | NTP-opsætning, globale pausetider og per-kamera pauseskemaer |
| **Indstillinger** | Tidszone og kendte hostnavne |
| **Sprog** | Skift mellem dansk og engelsk (eller tilføj nye sprogfiler) |
| **Logs** | Applikationslog direkte i browseren |
| **Backup** | Download/genopret konfiguration som XML |

## Netværksstyring

Hostname, IP-adresser og netværksindstillinger styres **ikke** fra CameraWebService.
Vi anbefaler [**Cockpit**](https://cockpit-project.org/) til dette formål — et professionelt webbaseret administrationspanel til Linux der kører direkte på Pi'en.

**Installation af Cockpit:**
```bash
sudo apt install -y cockpit
sudo systemctl enable --now cockpit.socket
```

Cockpit åbnes på: `http://<pi-ip>:9090`

Her kan du ændre hostname, konfigurere statisk IP, overvåge CPU/RAM og styre services — alt fra browseren.

## Sprogfiler

Sprogfiler ligger i mappen `language/`. Tilføj en ny fil `language/xx.json` (se `da.json` som skabelon) for at gøre et nyt sprog tilgængeligt i **Sprog**-fanen. Filen skal indeholde felterne `version`, `locale`, `name`, `nativeName`, `fallback` og `translations`.

## FTP/SFTP upload

Udfyld host, port, brugernavn, adgangskode og remote-mappe under **Upload**. Brug "Test upload" på dashboard for at verificere forbindelsen.

## FTPS

Vælg metoden `ftps` og angiv de samme felter som FTP.

## UniFi Protect RTSPS

Angiv Protect stream-URL i RTSP-URL-feltet: `rtsps://192.168.x.x/...`

## WordPress-integration

Zip mappen `wordpress-plugin/camera-snapshot` og installér i WordPress.

- REST endpoint: `/wp-json/camera-snapshot/v1/upload`
- Shortcode: `[camera_snapshot]`

## Fejlfinding

```bash
# Vis live log
sudo journalctl -u CameraWebService -f

# Tjek servicestatus
sudo systemctl status CameraWebService

# Genstart tjenesten
sudo systemctl restart CameraWebService
```

Applikationsloggen er også tilgængelig i web-UI under **Logs**.

## Backup og gendannelse

Under **Backup** kan du downloade konfigurationen som XML — enten med eller uden adgangskoder. Brug den fulde backup til at flytte installationen til ny hardware.

## Sikkerhed

- Konfiguration gemmes i `/opt/CameraWebService/config.json` med `chmod 600`
- Passwords og tokens vises ikke i UI efter de er gemt
- Session-nøglen genereres tilfældigt ved første opstart og gemmes i config
- Tjenesten kører som den uprivilegerede systembruger `camerawebservice`
