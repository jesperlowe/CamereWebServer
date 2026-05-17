# CameraWebService

**Version 3.1.0** — Webbaseret kameraservice til Raspberry Pi.

Henter snapshots fra RTSP/RTSPS-streams med `ffmpeg` og uploader direkte fra RAM (ingen permanent lokal JPG-fil). Integrerer med Track Status Light Server via en offentlig kamera-URL.

## Hardwarekrav

- Raspberry Pi 4 (eller nyere)
- SD-kort 16 GB+
- Netværk (Ethernet anbefales)

## Samlet installationsvejledning

### Trin 1 — Klargør SD-kort

1. Download og installer [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Vælg **Raspberry Pi OS Lite (64-bit)** som operativsystem.
3. Klik på tandhjulet (⚙) eller tryk **Ctrl+Shift+X** for at åbne *Advanced options*:
   - Sæt hostname, fx `rpicam01`
   - Aktivér SSH
   - Angiv brugernavn og adgangskode, fx `admin` / dit-password
   - Konfigurér WiFi hvis du ikke bruger Ethernet
4. Skriv image til SD-kortet og sæt det i Pi'en.

### Trin 2 — Find Pi'ens IP-adresse

Boot Pi'en og find dens IP-adresse — enten fra din router eller via SSH-scan:

```bash
# Fra en anden maskine på samme netværk:
ping rpicam01.local

# Eller find IP direkte på Pi'en (kræver skærm/tastatur):
hostname -I
```

Opret SSH-forbindelse:

```bash
ssh admin@rpicam01.local
# eller
ssh admin@<ip-adresse>
```

### Trin 3 — Opdatér systemet og installér Git

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git
```

### Trin 4 — Hent koden

```bash
cd ~
git clone https://github.com/jesperlowe/CameraWebService.git
cd CameraWebService
```

### Trin 5 — Kør installationsscriptet

```bash
sudo bash install.sh
```

Scriptet installerer automatisk:
- Python 3, python3-venv og ffmpeg
- Systembrugeren `camerawebservice`
- Koden i `/opt/CameraWebService`
- Et Python virtual environment med alle pakker
- Systemd-servicen `CameraWebService` (starter ved boot)

Når installationen er færdig vises adressen til webinterfacet:

```
Webinterface: http://<pi-ip>:8080
```

### Trin 6 — Åbn webinterfacet

Gå til `http://<pi-ip>:8080` i en browser.

- Brugernavn: `admin`
- Adgangskode: `admin`

Du tvinges til at vælge en ny adgangskode ved første login.

---

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
| **Indstillinger** | Tidszone, kendte hostnavne og Healthchecks.io |
| **Sprog** | Skift sprog, upload og download sprogfiler |
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

## Lyst og mørkt tema

Klik på solen/måne-ikonet øverst i navigationen for at skifte mellem mørkt og lyst tema. Valget gemmes i browseren (localStorage) og huskes på tværs af sessioner.

## Healthchecks.io

Under **Indstillinger** kan du angive en [healthchecks.io](https://healthchecks.io/) ping-URL. Tjenesten sender automatisk et ping efter hvert vellykket kamera-upload og pinger `/fail`-URL'en ved fejl. Dette giver overvågning og notifikationer hvis kameraet holder op med at uploade.

```
https://hc-ping.com/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

## Sprogfiler

Sprogfiler ligger i mappen `language/`. Du kan administrere dem direkte fra **Sprog**-fanen i web-UI'et:

- **Download** — Hent en eksisterende sprogfil som `.json` og brug den som skabelon.
- **Upload** — Upload en ny eller redigeret `.json`-sprogfil direkte til serveren uden SSH.

Manuelt: tilføj en ny fil `language/xx.json` (se `da.json` som skabelon). Filen skal indeholde felterne `version`, `locale`, `name`, `nativeName`, `fallback` og `translations`.

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
