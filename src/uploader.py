import ftplib
import io
import logging
from pathlib import PurePosixPath

import httpx
import paramiko

from src.config import AppConfig

logger = logging.getLogger("camera_uploader")


def _remote_path(cfg: AppConfig, filename: str) -> str:
    remote_dir = cfg.upload.sftp.remote_dir.rstrip("/")
    return f"{remote_dir}/{filename}" if filename else remote_dir


def upload_sftp(image_bytes: bytes, cfg: AppConfig, filename: str) -> None:
    s = cfg.upload.sftp
    path = _remote_path(cfg, filename)
    transport = paramiko.Transport((s.host, s.port or 22))
    try:
        if s.private_key_path:
            key = paramiko.RSAKey.from_private_key_file(s.private_key_path)
            transport.connect(username=s.username, pkey=key)
        else:
            transport.connect(username=s.username, password=s.password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        with sftp.open(path, "wb") as remote:
            remote.write(image_bytes)
        logger.info("SFTP upload OK: %s", path)
    finally:
        transport.close()


def upload_ftp(image_bytes: bytes, cfg: AppConfig, filename: str) -> None:
    s = cfg.upload.sftp
    path = _remote_path(cfg, filename)
    with ftplib.FTP() as ftp:
        ftp.connect(s.host, s.port or 21, timeout=20)
        ftp.login(s.username, s.password)
        ftp.storbinary(f"STOR {path}", io.BytesIO(image_bytes))
        logger.info("FTP upload OK: %s", path)


def upload_ftps(image_bytes: bytes, cfg: AppConfig, filename: str) -> None:
    s = cfg.upload.sftp
    path = _remote_path(cfg, filename)
    with ftplib.FTP_TLS() as ftp:
        ftp.connect(s.host, s.port or 21, timeout=20)
        ftp.login(s.username, s.password)
        ftp.prot_p()
        ftp.storbinary(f"STOR {path}", io.BytesIO(image_bytes))
        logger.info("FTPS upload OK: %s", path)


def upload_wordpress(image_bytes: bytes, cfg: AppConfig, filename: str) -> None:
    wp = cfg.upload.wordpress
    headers = {
        "Authorization": f"Bearer {wp.bearer_token}",
        "Content-Type": "image/jpeg",
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    resp = httpx.post(wp.endpoint, content=image_bytes, headers=headers, timeout=20)
    resp.raise_for_status()
    logger.info("WordPress upload OK: %s", filename)


def upload_image(image_bytes: bytes, cfg: AppConfig, filename: str = "snapshot.jpg") -> None:
    method = cfg.upload.method
    if method == "sftp":
        upload_sftp(image_bytes, cfg, filename)
    elif method == "ftp":
        upload_ftp(image_bytes, cfg, filename)
    elif method == "ftps":
        upload_ftps(image_bytes, cfg, filename)
    elif method == "wordpress":
        upload_wordpress(image_bytes, cfg, filename)
    else:
        raise RuntimeError(f"Ukendt uploadmetode: {method!r}")
