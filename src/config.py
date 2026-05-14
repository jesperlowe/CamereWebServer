import json
import os
import secrets
from dataclasses import dataclass, asdict, field
from pathlib import Path

import bcrypt

APP_VERSION = "3.0.0"

CONFIG_PATH = Path(os.environ.get("CAMERA_UPLOADER_CONFIG", "/opt/camera-uploader/config.json"))

MAX_CAMERAS = 5

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

DEFAULT_INTERVAL = 15


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


@dataclass
class AuthConfig:
    username: str = "admin"
    password_hash: str = field(default_factory=lambda: hash_password("admin"))
    force_password_change: bool = True
    session_secret: str = field(default_factory=lambda: secrets.token_hex(32))


@dataclass
class SFTPConfig:
    host: str = ""
    port: int = 21
    username: str = ""
    password: str = ""
    private_key_path: str = ""
    remote_dir: str = "/public_html/camera"


@dataclass
class WordpressConfig:
    endpoint: str = ""
    bearer_token: str = ""


@dataclass
class UploadConfig:
    method: str = "ftp"
    public_base_url: str = ""
    sftp: SFTPConfig = field(default_factory=SFTPConfig)
    wordpress: WordpressConfig = field(default_factory=WordpressConfig)


@dataclass
class NtpConfig:
    enabled: bool = True
    server: str = "pool.ntp.org"


@dataclass
class AppConfig:
    auth: AuthConfig = field(default_factory=AuthConfig)
    cameras: list = field(default_factory=lambda: [
        {
            "id": 1,
            "name": "Kamera 1",
            "rtsp_url": "",
            "enabled": True,
            "filename": "camera1.jpg",
            "capture_interval_minutes": DEFAULT_INTERVAL,
            "pause_schedule": [],
        }
    ])
    capture_interval_minutes: int = DEFAULT_INTERVAL  # global fallback
    upload: UploadConfig = field(default_factory=UploadConfig)
    ntp: NtpConfig = field(default_factory=NtpConfig)
    dark_periods: list = field(default_factory=list)  # global fallback
    timezone: str = "Europe/Copenhagen"
    allowed_hosts: list = field(default_factory=lambda: ["*"])


def _chmod_600(path: Path) -> None:
    path.chmod(0o600)


def _migrate_camera(cam: dict, global_interval: int, global_dark: list) -> dict:
    """Ensure every camera dict has per-camera interval and pause_schedule."""
    if "capture_interval_minutes" not in cam:
        cam["capture_interval_minutes"] = global_interval
    if "pause_schedule" not in cam:
        # Seed from global dark_periods on first migration so existing schedules carry over
        cam["pause_schedule"] = list(global_dark)
    return cam


def _migrate_legacy(data: dict) -> dict:
    """Migrate v1/v2 config to v3 (per-camera interval + pause_schedule, timezone, allowed_hosts)."""
    # v1 → v2: single camera → cameras list
    if "camera" in data and "cameras" not in data:
        old = data.pop("camera")
        data["cameras"] = [{
            "id": 1,
            "name": "Kamera 1",
            "rtsp_url": old.get("rtsp_url", ""),
            "enabled": True,
            "filename": "camera1.jpg",
        }]
        data["capture_interval_minutes"] = old.get("capture_interval_minutes", DEFAULT_INTERVAL)

    if "ntp" not in data:
        data["ntp"] = {"enabled": True, "server": "pool.ntp.org"}
    if "dark_periods" not in data:
        data["dark_periods"] = []
    if "timezone" not in data:
        data["timezone"] = "Europe/Copenhagen"
    if "allowed_hosts" not in data:
        data["allowed_hosts"] = ["*"]

    # Migrate remote_path → remote_dir
    sftp = data.get("upload", {}).get("sftp", {})
    if "remote_path" in sftp and "remote_dir" not in sftp:
        import posixpath
        old_path = sftp.pop("remote_path")
        sftp["remote_dir"] = posixpath.dirname(old_path) or old_path

    # v2 → v3: add per-camera fields
    global_interval = data.get("capture_interval_minutes", DEFAULT_INTERVAL)
    global_dark = data.get("dark_periods", [])
    data["cameras"] = [_migrate_camera(cam, global_interval, global_dark) for cam in data.get("cameras", [])]

    return data


def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        cfg = AppConfig()
        save_config(cfg)
        return cfg
    data = json.loads(CONFIG_PATH.read_text())
    data = _migrate_legacy(data)
    ntp_data = data.get("ntp", {})
    sftp_data = data.get("upload", {}).get("sftp", {})
    return AppConfig(
        auth=AuthConfig(**data.get("auth", {})),
        cameras=data.get("cameras", []),
        capture_interval_minutes=data.get("capture_interval_minutes", DEFAULT_INTERVAL),
        upload=UploadConfig(
            method=data.get("upload", {}).get("method", "ftp"),
            public_base_url=data.get("upload", {}).get("public_base_url", ""),
            sftp=SFTPConfig(**sftp_data),
            wordpress=WordpressConfig(**data.get("upload", {}).get("wordpress", {})),
        ),
        ntp=NtpConfig(**ntp_data),
        dark_periods=data.get("dark_periods", []),
        timezone=data.get("timezone", "Europe/Copenhagen"),
        allowed_hosts=data.get("allowed_hosts", ["*"]),
    )


def save_config(cfg: AppConfig) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(asdict(cfg), indent=2))
    _chmod_600(CONFIG_PATH)
