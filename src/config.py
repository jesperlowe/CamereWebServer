import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

CONFIG_PATH = Path(os.environ.get("CAMERA_UPLOADER_CONFIG", "/opt/camera-uploader/config.json"))


@dataclass
class AuthConfig:
    username: str = "admin"
    password_hash: str = pwd_context.hash("admin")
    force_password_change: bool = True


@dataclass
class CameraConfig:
    rtsp_url: str = ""
    capture_interval_minutes: int = 15


@dataclass
class SFTPConfig:
    host: str = ""
    port: int = 22
    username: str = ""
    password: str = ""
    private_key_path: str = ""
    remote_path: str = "/public_html/camera/latest.jpg"


@dataclass
class WordpressConfig:
    endpoint: str = ""
    bearer_token: str = ""


@dataclass
class UploadConfig:
    method: str = "sftp"
    sftp: SFTPConfig = field(default_factory=SFTPConfig)
    wordpress: WordpressConfig = field(default_factory=WordpressConfig)


@dataclass
class AppConfig:
    auth: AuthConfig = field(default_factory=AuthConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    upload: UploadConfig = field(default_factory=UploadConfig)


def _chmod_600(path: Path) -> None:
    path.chmod(0o600)


def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        cfg = AppConfig()
        save_config(cfg)
        return cfg
    data = json.loads(CONFIG_PATH.read_text())
    return AppConfig(
        auth=AuthConfig(**data.get("auth", {})),
        camera=CameraConfig(**data.get("camera", {})),
        upload=UploadConfig(
            method=data.get("upload", {}).get("method", "sftp"),
            sftp=SFTPConfig(**data.get("upload", {}).get("sftp", {})),
            wordpress=WordpressConfig(**data.get("upload", {}).get("wordpress", {})),
        ),
    )


def save_config(cfg: AppConfig) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(asdict(cfg), indent=2))
    _chmod_600(CONFIG_PATH)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)
