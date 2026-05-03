import ftplib
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


def upload_ftp(image_bytes: bytes, cfg: AppConfig) -> None:
    s = cfg.upload.sftp
    remote_path = PurePosixPath(s.remote_path)
    with ftplib.FTP() as ftp:
        ftp.connect(s.host, s.port or 21, timeout=20)
        ftp.login(s.username, s.password)
        logger.info("FTP forbundet til %s", s.host)
        ftp.storbinary(f"STOR {remote_path}", io.BytesIO(image_bytes))
        logger.info("FTP upload fuldført: %s", remote_path)


def upload_ftps(image_bytes: bytes, cfg: AppConfig) -> None:
    s = cfg.upload.sftp
    remote_path = PurePosixPath(s.remote_path)
    with ftplib.FTP_TLS() as ftp:
        ftp.connect(s.host, s.port or 21, timeout=20)
        ftp.login(s.username, s.password)
        ftp.prot_p()  # krypteret datakanal
        logger.info("FTPS forbundet til %s", s.host)
        ftp.storbinary(f"STOR {remote_path}", io.BytesIO(image_bytes))
        logger.info("FTPS upload fuldført: %s", remote_path)


def upload_wordpress(image_bytes: bytes, cfg: AppConfig) -> None:
    wp = cfg.upload.wordpress
    headers = {
        "Authorization": f"Bearer {wp.bearer_token}",
        "Content-Type": "image/jpeg",
    }
    resp = httpx.post(wp.endpoint, content=image_bytes, headers=headers, timeout=20)
    resp.raise_for_status()


def upload_image(image_bytes: bytes, cfg: AppConfig) -> None:
    method = cfg.upload.method
    if method == "sftp":
        upload_sftp(image_bytes, cfg)
    elif method == "ftp":
        upload_ftp(image_bytes, cfg)
    elif method == "ftps":
        upload_ftps(image_bytes, cfg)
    elif method == "wordpress":
        upload_wordpress(image_bytes, cfg)
    else:
        raise RuntimeError(f"Ukendt uploadmetode: {method!r}")
