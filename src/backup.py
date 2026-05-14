"""
XML backup/restore for the full application configuration.

The exported XML contains all settings including credentials.
Treat the file as sensitive and store it securely.
"""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from src.config import (
    AppConfig, AuthConfig, NtpConfig,
    SFTPConfig, UploadConfig, WordpressConfig,
    hash_password, load_config,
)

_VERSION = "3"


# ── Export ────────────────────────────────────────────────────────────────────

def _set(parent: ET.Element, tag: str, value: Any) -> ET.Element:
    el = ET.SubElement(parent, tag)
    el.text = str(value).lower() if isinstance(value, bool) else str(value or "")
    return el


def config_to_xml(cfg: AppConfig) -> bytes:
    root = ET.Element("camera-uploader-backup")
    root.set("version", _VERSION)
    root.set("exported", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    # Auth
    auth = ET.SubElement(root, "auth")
    _set(auth, "username",              cfg.auth.username)
    _set(auth, "password_hash",         cfg.auth.password_hash)
    _set(auth, "force_password_change", cfg.auth.force_password_change)
    _set(auth, "session_secret",        cfg.auth.session_secret)

    # Capture interval
    _set(root, "capture_interval_minutes", cfg.capture_interval_minutes)

    # System
    _set(root, "timezone",      cfg.timezone)
    hosts_el = ET.SubElement(root, "allowed_hosts")
    for h in cfg.allowed_hosts:
        _set(hosts_el, "host", h)

    # Cameras
    cameras_el = ET.SubElement(root, "cameras")
    for cam in cfg.cameras:
        cam_el = ET.SubElement(cameras_el, "camera")
        cam_el.set("id", str(cam.get("id", "")))
        _set(cam_el, "name",                     cam.get("name", ""))
        _set(cam_el, "rtsp_url",                 cam.get("rtsp_url", ""))
        _set(cam_el, "enabled",                  cam.get("enabled", True))
        _set(cam_el, "filename",                 cam.get("filename", ""))
        _set(cam_el, "capture_interval_minutes", cam.get("capture_interval_minutes", 15))
        pause_el = ET.SubElement(cam_el, "pause_schedule")
        for p in cam.get("pause_schedule", []):
            p_el = ET.SubElement(pause_el, "period")
            p_el.set("id", str(p.get("id", "")))
            _set(p_el, "label",   p.get("label", ""))
            _set(p_el, "day",     p.get("day", "all"))
            _set(p_el, "start",   p.get("start", "22:00"))
            _set(p_el, "end",     p.get("end",   "06:00"))
            _set(p_el, "enabled", p.get("enabled", True))

    # Upload
    upload_el = ET.SubElement(root, "upload")
    _set(upload_el, "method", cfg.upload.method)
    sftp_el = ET.SubElement(upload_el, "sftp")
    _set(sftp_el, "host",             cfg.upload.sftp.host)
    _set(sftp_el, "port",             cfg.upload.sftp.port)
    _set(sftp_el, "username",         cfg.upload.sftp.username)
    _set(sftp_el, "password",         cfg.upload.sftp.password)
    _set(sftp_el, "private_key_path", cfg.upload.sftp.private_key_path)
    _set(sftp_el, "remote_dir",       cfg.upload.sftp.remote_dir)
    wp_el = ET.SubElement(upload_el, "wordpress")
    _set(wp_el, "endpoint",     cfg.upload.wordpress.endpoint)
    _set(wp_el, "bearer_token", cfg.upload.wordpress.bearer_token)

    # NTP
    ntp_el = ET.SubElement(root, "ntp")
    _set(ntp_el, "enabled", cfg.ntp.enabled)
    _set(ntp_el, "server",  cfg.ntp.server)

    # Dark periods
    dark_el = ET.SubElement(root, "dark_periods")
    for p in cfg.dark_periods:
        p_el = ET.SubElement(dark_el, "period")
        p_el.set("id", str(p.get("id", "")))
        _set(p_el, "label",   p.get("label", ""))
        _set(p_el, "day",     p.get("day", "all"))
        _set(p_el, "start",   p.get("start", "22:00"))
        _set(p_el, "end",     p.get("end", "06:00"))
        _set(p_el, "enabled", p.get("enabled", True))

    ET.indent(root, space="  ")
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode").encode()


def config_to_xml_no_auth(cfg: AppConfig) -> bytes:
    """Export config without password hash, session secret or upload credentials."""
    safe = copy.deepcopy(cfg)
    safe.auth.password_hash = hash_password("CHANGE_ME")
    safe.auth.session_secret = ""
    safe.auth.force_password_change = True
    safe.upload.sftp.password = ""
    safe.upload.sftp.private_key_path = ""
    safe.upload.wordpress.bearer_token = ""
    return config_to_xml(safe)


# ── Import ────────────────────────────────────────────────────────────────────

def _bool(text: str | None) -> bool:
    return (text or "").strip().lower() in ("true", "1", "yes")


def _int(text: str | None, default: int = 0) -> int:
    try:
        return int(text or default)
    except ValueError:
        return default


def xml_to_config(xml_bytes: bytes) -> AppConfig:
    root = ET.fromstring(xml_bytes.decode())

    if root.tag != "camera-uploader-backup":
        raise ValueError("Ugyldig backup-fil: forventet <camera-uploader-backup>")

    def txt(parent: ET.Element, tag: str, default: str = "") -> str:
        el = parent.find(tag)
        return el.text.strip() if el is not None and el.text else default

    # Auth
    auth_el = root.find("auth")
    auth = AuthConfig(
        username             = txt(auth_el, "username", "admin") if auth_el is not None else "admin",
        password_hash        = txt(auth_el, "password_hash", "") if auth_el is not None else "",
        force_password_change= _bool(txt(auth_el, "force_password_change", "false")) if auth_el is not None else False,
        session_secret       = txt(auth_el, "session_secret", "") if auth_el is not None else "",
    )

    interval = _int(txt(root, "capture_interval_minutes", "15"), 15)

    # System
    timezone     = txt(root, "timezone", "Europe/Copenhagen")
    allowed_hosts = [el.text.strip() for el in root.findall("allowed_hosts/host") if el.text]
    if not allowed_hosts:
        allowed_hosts = ["*"]

    # Cameras
    cameras = []
    for cam_el in root.findall("cameras/camera"):
        pause_schedule = []
        for p_el in cam_el.findall("pause_schedule/period"):
            pause_schedule.append({
                "id":      _int(p_el.get("id", "1")),
                "label":   txt(p_el, "label"),
                "day":     txt(p_el, "day", "all"),
                "start":   txt(p_el, "start", "22:00"),
                "end":     txt(p_el, "end",   "06:00"),
                "enabled": _bool(txt(p_el, "enabled", "true")),
            })
        cameras.append({
            "id":                       _int(cam_el.get("id", "1")),
            "name":                     txt(cam_el, "name", "Kamera"),
            "rtsp_url":                 txt(cam_el, "rtsp_url"),
            "enabled":                  _bool(txt(cam_el, "enabled", "true")),
            "filename":                 txt(cam_el, "filename", "camera.jpg"),
            "capture_interval_minutes": _int(txt(cam_el, "capture_interval_minutes", "15"), 15),
            "pause_schedule":           pause_schedule,
        })
    if not cameras:
        cameras = [{"id": 1, "name": "Kamera 1", "rtsp_url": "", "enabled": True,
                    "filename": "camera1.jpg", "capture_interval_minutes": 15, "pause_schedule": []}]

    # Upload
    upload_el  = root.find("upload")
    sftp_el    = upload_el.find("sftp")    if upload_el is not None else None
    wp_el      = upload_el.find("wordpress") if upload_el is not None else None
    upload = UploadConfig(
        method    = txt(upload_el, "method", "ftp") if upload_el is not None else "ftp",
        sftp      = SFTPConfig(
            host            = txt(sftp_el, "host")            if sftp_el is not None else "",
            port            = _int(txt(sftp_el, "port", "21"), 21) if sftp_el is not None else 21,
            username        = txt(sftp_el, "username")        if sftp_el is not None else "",
            password        = txt(sftp_el, "password")        if sftp_el is not None else "",
            private_key_path= txt(sftp_el, "private_key_path")if sftp_el is not None else "",
            remote_dir      = txt(sftp_el, "remote_dir", "/public_html/camera") if sftp_el is not None else "/public_html/camera",
        ),
        wordpress = WordpressConfig(
            endpoint     = txt(wp_el, "endpoint")     if wp_el is not None else "",
            bearer_token = txt(wp_el, "bearer_token") if wp_el is not None else "",
        ),
    )

    # NTP
    ntp_el = root.find("ntp")
    ntp = NtpConfig(
        enabled = _bool(txt(ntp_el, "enabled", "true")) if ntp_el is not None else True,
        server  = txt(ntp_el, "server", "pool.ntp.org") if ntp_el is not None else "pool.ntp.org",
    )

    # Dark periods
    dark_periods = []
    for p_el in root.findall("dark_periods/period"):
        dark_periods.append({
            "id":      _int(p_el.get("id", "1")),
            "label":   txt(p_el, "label"),
            "day":     txt(p_el, "day", "all"),
            "start":   txt(p_el, "start", "22:00"),
            "end":     txt(p_el, "end",   "06:00"),
            "enabled": _bool(txt(p_el, "enabled", "true")),
        })

    return AppConfig(
        auth=auth,
        cameras=cameras,
        capture_interval_minutes=interval,
        upload=upload,
        ntp=ntp,
        dark_periods=dark_periods,
        timezone=timezone,
        allowed_hosts=allowed_hosts,
    )
