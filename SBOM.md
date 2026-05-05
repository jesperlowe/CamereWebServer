# Software Bill of Materials (SBOM)

Generated for: **CameraWebService version2**

## Runtime Dependencies

| Package | Version | License | Purpose |
|---------|---------|---------|---------|
| fastapi | 0.115.0 | MIT | Web framework |
| uvicorn[standard] | 0.30.6 | BSD-3-Clause | ASGI server |
| jinja2 | 3.1.4 | BSD-3-Clause | HTML templating |
| python-multipart | 0.0.9 | Apache-2.0 | Form parsing |
| paramiko | 3.4.1 | LGPL-2.1 | SFTP upload |
| httpx | 0.27.2 | BSD-3-Clause | HTTP upload (WordPress) |
| bcrypt | ≥ 4.0 | Apache-2.0 | Password hashing |
| itsdangerous | 2.2.0 | BSD-3-Clause | Session signing |
| ntplib | ≥ 0.4.0 | MIT | NTP time check |

## System Dependencies (installed via apt)

| Package | Purpose |
|---------|---------|
| ffmpeg | RTSP snapshot capture |
| python3 | Runtime |
| python3-venv | Virtual environment |

## Development / Build Dependencies

None — no build step required.

## License Compatibility

All runtime dependencies use permissive licenses (MIT, BSD, Apache-2.0, LGPL-2.1).
The project itself is MIT licensed. LGPL-2.1 (paramiko) is compatible with MIT
for use as a library without modification.
