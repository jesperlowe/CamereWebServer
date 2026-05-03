import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeSerializer

from src.backup import config_to_xml, xml_to_config
from src.capture import capture_snapshot
from src.config import MAX_CAMERAS, WEEKDAYS, hash_password, load_config, save_config, verify_password
from src.ntp_sync import check_ntp
from src.schedule_check import is_dark_time
from src.uploader import upload_image

app = FastAPI(title="Camera Uploader")
app.mount("/static", StaticFiles(directory="src/static"), name="static")
templates = Jinja2Templates(directory="src/templates")

def _get_serializer() -> URLSafeSerializer:
    """Load session secret from config so each installation has a unique key."""
    return URLSafeSerializer(load_config().auth.session_secret)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("camera_uploader")
log_buffer = deque(maxlen=200)

# Per-camera state keyed by camera id
state = {
    "ntp": {},
    "dark": False,
    "dark_reason": "",
    "cameras": {},   # {cam_id: {last_upload, last_error, name, last_image}}
    "last_error": "-",
}


class BufferHandler(logging.Handler):
    def emit(self, record):
        log_buffer.appendleft(self.format(record))


logger.addHandler(BufferHandler())


# ── Auth helpers ─────────────────────────────────────────────────────────────

def _authed(request: Request) -> bool:
    token = request.cookies.get("session")
    if not token:
        return False
    try:
        return bool(_get_serializer().loads(token).get("u"))
    except Exception:
        return False


def _require_auth(request: Request) -> None:
    if not _authed(request):
        raise HTTPException(status_code=302, headers={"Location": "/login"})


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    cfg = load_config()
    if username != cfg.auth.username or not verify_password(password, cfg.auth.password_hash):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Forkert login"})
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(
        "session",
        _get_serializer().dumps({"u": username}),
        httponly=True,
        samesite="strict",
    )
    return resp


@app.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("session")
    return resp


@app.post("/change-password")
def change_password(request: Request, password: str = Form(...)):
    _require_auth(request)
    cfg = load_config()
    cfg.auth.password_hash = hash_password(password)
    cfg.auth.force_password_change = False
    save_config(cfg)
    return RedirectResponse("/", status_code=302)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/")
def dashboard(request: Request):
    _require_auth(request)
    cfg = load_config()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "state": state,
        "cameras": cfg.cameras,
        "force": cfg.auth.force_password_change,
    })


# ── Camera management ─────────────────────────────────────────────────────────

@app.get("/cameras")
def cameras_page(request: Request):
    _require_auth(request)
    cfg = load_config()
    return templates.TemplateResponse("cameras.html", {
        "request": request,
        "cameras": cfg.cameras,
        "interval": cfg.capture_interval_minutes,
        "max_cameras": MAX_CAMERAS,
    })


@app.post("/cameras/interval")
def save_interval(request: Request, interval: int = Form(...)):
    _require_auth(request)
    cfg = load_config()
    cfg.capture_interval_minutes = max(1, interval)
    save_config(cfg)
    return RedirectResponse("/cameras", status_code=302)


@app.post("/cameras/add")
def add_camera(request: Request,
               name: str = Form(...),
               rtsp_url: str = Form(""),
               filename: str = Form(...),
               enabled: str = Form("off")):
    _require_auth(request)
    cfg = load_config()
    if len(cfg.cameras) >= MAX_CAMERAS:
        return RedirectResponse("/cameras", status_code=302)
    next_id = max((c.get("id", 0) for c in cfg.cameras), default=0) + 1
    cfg.cameras.append({
        "id": next_id,
        "name": name,
        "rtsp_url": rtsp_url,
        "enabled": enabled == "on",
        "filename": filename or f"camera{next_id}.jpg",
    })
    save_config(cfg)
    return RedirectResponse("/cameras", status_code=302)


@app.post("/cameras/{cam_id}/save")
def save_camera(request: Request, cam_id: int,
                name: str = Form(...),
                rtsp_url: str = Form(""),
                filename: str = Form(...),
                enabled: str = Form("off")):
    _require_auth(request)
    cfg = load_config()
    for cam in cfg.cameras:
        if cam.get("id") == cam_id:
            cam["name"]     = name
            cam["rtsp_url"] = rtsp_url
            cam["filename"] = filename or cam["filename"]
            cam["enabled"]  = enabled == "on"
            break
    save_config(cfg)
    return RedirectResponse("/cameras", status_code=302)


@app.post("/cameras/{cam_id}/delete")
def delete_camera(request: Request, cam_id: int):
    _require_auth(request)
    cfg = load_config()
    cfg.cameras = [c for c in cfg.cameras if c.get("id") != cam_id]
    save_config(cfg)
    return RedirectResponse("/cameras", status_code=302)


@app.post("/cameras/{cam_id}/test")
def test_camera(request: Request, cam_id: int):
    _require_auth(request)
    cfg = load_config()
    cam = next((c for c in cfg.cameras if c.get("id") == cam_id), None)
    if not cam:
        return RedirectResponse("/cameras", status_code=302)
    img = capture_snapshot(cam["rtsp_url"])
    state["cameras"].setdefault(cam_id, {})["last_image"] = img
    state["cameras"][cam_id]["name"] = cam.get("name", "")
    return RedirectResponse("/", status_code=302)


@app.post("/cameras/{cam_id}/upload-test")
def upload_test_camera(request: Request, cam_id: int):
    _require_auth(request)
    cfg = load_config()
    cam = next((c for c in cfg.cameras if c.get("id") == cam_id), None)
    if not cam:
        return RedirectResponse("/", status_code=302)
    cam_state = state["cameras"].get(cam_id, {})
    img = cam_state.get("last_image") or capture_snapshot(cam["rtsp_url"])
    upload_image(img, cfg, cam.get("filename", f"camera{cam_id}.jpg"))
    state["cameras"].setdefault(cam_id, {}).update({
        "last_upload": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "last_error": "-",
    })
    return RedirectResponse("/", status_code=302)


@app.get("/test-image/{cam_id}")
def test_image(request: Request, cam_id: int):
    _require_auth(request)
    img = state["cameras"].get(cam_id, {}).get("last_image", b"")
    return Response(content=img, media_type="image/jpeg")


# ── Upload settings ───────────────────────────────────────────────────────────

@app.get("/upload")
def upload_page(request: Request):
    _require_auth(request)
    return templates.TemplateResponse("upload.html", {"request": request, "cfg": load_config()})


@app.post("/upload")
def save_upload(request: Request,
                method: str = Form(...),
                sftp_host: str = Form(""),
                sftp_port: int = Form(21),
                sftp_username: str = Form(""),
                sftp_password: str = Form(""),
                sftp_key: str = Form(""),
                remote_dir: str = Form(""),
                wp_endpoint: str = Form(""),
                wp_token: str = Form("")):
    _require_auth(request)
    cfg = load_config()
    cfg.upload.method             = method
    cfg.upload.sftp.host          = sftp_host
    cfg.upload.sftp.port          = sftp_port
    cfg.upload.sftp.username      = sftp_username
    cfg.upload.sftp.remote_dir    = remote_dir
    cfg.upload.sftp.private_key_path = sftp_key
    if sftp_password:
        cfg.upload.sftp.password  = sftp_password
    cfg.upload.wordpress.endpoint = wp_endpoint
    if wp_token:
        cfg.upload.wordpress.bearer_token = wp_token
    save_config(cfg)
    return RedirectResponse("/upload", status_code=302)


# ── Schedule (dark periods + NTP) ─────────────────────────────────────────────

@app.get("/schedule")
def schedule_page(request: Request):
    _require_auth(request)
    cfg = load_config()
    return templates.TemplateResponse("schedule.html", {
        "request": request,
        "cfg": cfg,
        "weekdays": WEEKDAYS,
        "ntp_state": state.get("ntp", {}),
    })


@app.post("/schedule/ntp")
def save_ntp(request: Request,
             ntp_enabled: str = Form("off"),
             ntp_server: str = Form("pool.ntp.org")):
    _require_auth(request)
    cfg = load_config()
    cfg.ntp.enabled = ntp_enabled == "on"
    cfg.ntp.server  = ntp_server.strip() or "pool.ntp.org"
    save_config(cfg)
    return RedirectResponse("/schedule", status_code=302)


@app.post("/schedule/ntp/test")
def test_ntp(request: Request):
    _require_auth(request)
    cfg = load_config()
    state["ntp"] = check_ntp(cfg.ntp.server)
    return RedirectResponse("/schedule", status_code=302)


@app.post("/schedule/dark/add")
def add_dark_period(request: Request,
                    label: str = Form(""),
                    day: str = Form("all"),
                    start: str = Form("22:00"),
                    end: str = Form("06:00"),
                    enabled: str = Form("off")):
    _require_auth(request)
    cfg = load_config()
    next_id = max((p.get("id", 0) for p in cfg.dark_periods), default=0) + 1
    cfg.dark_periods.append({
        "id": next_id,
        "label": label,
        "day": day,
        "start": start,
        "end": end,
        "enabled": enabled == "on",
    })
    save_config(cfg)
    return RedirectResponse("/schedule", status_code=302)


@app.post("/schedule/dark/{period_id}/toggle")
def toggle_dark_period(request: Request, period_id: int):
    _require_auth(request)
    cfg = load_config()
    for p in cfg.dark_periods:
        if p.get("id") == period_id:
            p["enabled"] = not p.get("enabled", True)
            break
    save_config(cfg)
    return RedirectResponse("/schedule", status_code=302)


@app.post("/schedule/dark/{period_id}/delete")
def delete_dark_period(request: Request, period_id: int):
    _require_auth(request)
    cfg = load_config()
    cfg.dark_periods = [p for p in cfg.dark_periods if p.get("id") != period_id]
    save_config(cfg)
    return RedirectResponse("/schedule", status_code=302)


# ── Backup / Restore ──────────────────────────────────────────────────────────

@app.get("/backup")
def backup_page(request: Request):
    _require_auth(request)
    return templates.TemplateResponse("backup.html", {"request": request})


@app.get("/backup/download")
def backup_download(request: Request):
    _require_auth(request)
    cfg = load_config()
    xml_bytes = config_to_xml(cfg)
    filename = datetime.now().strftime("backup_%Y%m%d_%H%M%S.xml")
    return Response(
        content=xml_bytes,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/backup/restore")
async def backup_restore(request: Request, file: UploadFile = File(...)):
    _require_auth(request)
    content = await file.read()
    try:
        cfg = xml_to_config(content)
        save_config(cfg)
        logger.info("Konfiguration genoprettet fra XML-backup.")
        return templates.TemplateResponse("backup.html", {
            "request": request,
            "success": "Konfigurationen er genoprettet. Genstart tjenesten hvis scheduleren ikke reagerer.",
        })
    except Exception as exc:
        logger.error("Backup-gendannelse fejlede: %s", exc)
        return templates.TemplateResponse("backup.html", {
            "request": request,
            "error": f"Kunne ikke læse backup-filen: {exc}",
        })


# ── Logs ──────────────────────────────────────────────────────────────────────

@app.get("/logs")
def logs_page(request: Request):
    _require_auth(request)
    return templates.TemplateResponse("logs.html", {"request": request, "logs": list(log_buffer)})


# ── Scheduler ─────────────────────────────────────────────────────────────────

def scheduler_loop():
    while True:
        try:
            cfg = load_config()

            # NTP check
            if cfg.ntp.enabled:
                ntp_result = check_ntp(cfg.ntp.server)
                state["ntp"] = ntp_result
                if not ntp_result["ok"]:
                    logger.warning("NTP-tjek fejlede: %s", ntp_result.get("error"))

            # Dark period check
            dark, reason = is_dark_time(cfg.dark_periods)
            state["dark"] = dark
            state["dark_reason"] = reason
            if dark:
                logger.info("Mørketid aktiv (%s) — springer over optagelse.", reason)
            else:
                for cam in cfg.cameras:
                    if not cam.get("enabled"):
                        continue
                    rtsp = cam.get("rtsp_url", "")
                    if not rtsp:
                        continue
                    cam_id = cam.get("id", 0)
                    filename = cam.get("filename") or f"camera{cam_id}.jpg"
                    try:
                        img = capture_snapshot(rtsp)
                        upload_image(img, cfg, filename)
                        state["cameras"].setdefault(cam_id, {}).update({
                            "name": cam.get("name", ""),
                            "last_upload": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                            "last_error": "-",
                        })
                    except Exception as exc:
                        logger.error("Kamera '%s' fejl: %s", cam.get("name"), exc)
                        state["cameras"].setdefault(cam_id, {}).update({
                            "name": cam.get("name", ""),
                            "last_error": str(exc),
                        })

        except Exception as exc:
            logger.error("Scheduler fejl: %s", exc)
            state["last_error"] = str(exc)
        finally:
            interval = max(load_config().capture_interval_minutes, 1)
            threading.Event().wait(interval * 60)


@app.on_event("startup")
async def startup_event():
    threading.Thread(target=scheduler_loop, daemon=True).start()
