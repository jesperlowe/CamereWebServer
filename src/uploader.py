import io
import logging
from pathlib import PurePosixPath

import httpx
import paramiko

from src.config import AppConfig

logger = logging.getLogger("camera_uploader")


def upload_sftp(image_bytes: bytes, cfg: AppConfig) -> None:
    s = cfg.upload.sftp
    transport = paramiko.Transport((s.host, s.port))
    try:
        if s.private_key_path:
            key = paramiko.RSAKey.from_private_key_file(s.private_key_path)
            transport.connect(username=s.username, pkey=key)
        else:
            transport.connect(username=s.username, password=s.password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        with sftp.open(s.remote_path, "wb") as remote:
            remote.write(image_bytes)
    finally:
        transport.close()


def upload_wordpress(image_bytes: bytes, cfg: AppConfig) -> None:
    wp = cfg.upload.wordpress
    headers = {
        "Authorization": f"Bearer {wp.bearer_token}",
        "Content-Type": "image/jpeg",
    }
    resp = httpx.post(wp.endpoint, content=image_bytes, headers=headers, timeout=20)
    resp.raise_for_status()


def upload_image(image_bytes: bytes, cfg: AppConfig) -> None:
    if cfg.upload.method == "sftp":
        upload_sftp(image_bytes, cfg)
    elif cfg.upload.method == "wordpress":
        upload_wordpress(image_bytes, cfg)
    else:
        raise RuntimeError("Ukendt uploadmetode")
