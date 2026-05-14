import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone

from fastapi import FastAPI, Form, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeSerializer

from src.backup import config_to_xml, config_to_xml_no_auth, xml_to_config
from src.capture import capture_snapshot
from src.config import APP_VERSION, DEFAULT_INTERVAL, MAX_CAMERAS, WEEKDAYS, hash_password, load_config, save_config, verify_password
from src.ntp_sync import check_ntp
from src.schedule_check import is_dark_time
from src.uploader import upload_image

app = FastAPI(title="CameraWebService")
app.mount("/static", StaticFiles(directory="src/static"), name="static")
templates = Jinja2Templates(directory="src/templates")
templates.env.globals["APP_VERSION"] = APP_VERSION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("camera_uploader")
log_buffer = deque(maxlen=200)

# ── Session serializer — cached so load_config() is not called on every request ──
# Updated whenever the session secret is changed (password change or first save).
_serializer: URLSafeSerializer | None = None


def _get_serializer() -> URLSafeSerializer:
    global _serializer
    if _serializer is None:
        _serializer = URLSafeSerializer(load_config().auth.session_secret)
    return _serializer


def _refresh_serializer() -> None:
    """Call after any save_config() that may change auth.session_secret."""
    global _serializer
    _serializer = URLSafeSerializer(load_config().auth.session_secret)


# Per-camera state keyed by camera id
state = {
    "ntp": {},
    "dark": False,
    "dark_reason": "",
    "cameras": {},   # {cam_id: {last_upload, last_error, name, last_image}}
    "last_error": "-",
}

# Per-camera next-fire time (monotonic seconds)
_cam_next_fire: dict[int, float] = {}


class BufferHandler(logging.Handler):
    def emit(self, record):
        log_buffer.appendleft(self.format(record))


logger.addHandler(BufferHandler())


@app.on_event("startup")
async def startup_event():
    # Persist any migrated fields (e.g. session_secret) so auth survives restarts
    try:
        cfg = load_config()
        save_config(cfg)
    except Exception as exc:
        logger.error("Kunne ikke gemme konfiguration ved opstart: %s", exc)
    _refresh_serializer()
    threading.Thread(target=scheduler_loop, daemon=True).start()


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _authed(request: Request) -> bool:
    token = request.cookies.get("session")
    if not token:
        return False
    try:
        return bool(_get_serializer().loads(token).get("u"))
    except (BadSignature, SignatureExpired):
        return False
    except Exception as exc:
        logger.warning("Auth-fejl (uventet): %s", exc)
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
    _refresh_serializer()
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
        "weekdays": WEEKDAYS,
    })


@app.post("/cameras/add")
def add_camera(request: Request,
               name: str = Form(...),
               rtsp_url: str = Form(""),
               filename: str = Form(...),
               enabled: str = Form("off"),
               capture_interval_minutes: int = Form(DEFAULT_INTERVAL)):
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
        "capture_interval_minutes": max(1, capture_interval_minutes),
        "pause_schedule": [],
    })
    save_config(cfg)
    return RedirectResponse("/cameras", status_code=302)


@app.post("/cameras/{cam_id}/save")
def save_camera(request: Request, cam_id: int,
                name: str = Form(...),
                rtsp_url: str = Form(""),
                filename: str = Form(...),
                enabled: str = Form("off"),
                capture_interval_minutes: int = Form(DEFAULT_INTERVAL)):
    _require_auth(request)
    cfg = load_config()
    for cam in cfg.cameras:
        if cam.get("id") == cam_id:
            cam["name"]                    = name
            cam["rtsp_url"]               = rtsp_url
            cam["filename"]               = filename or cam["filename"]
            cam["enabled"]                = enabled == "on"
            cam["capture_interval_minutes"] = max(1, capture_interval_minutes)
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


# ── Per-camera pause schedule ─────────────────────────────────────────────────

@app.post("/cameras/{cam_id}/pause/add")
def add_cam_pause(request: Request, cam_id: int,
                  label: str = Form(""),
                  day: str = Form("all"),
                  start: str = Form("22:00"),
                  end: str = Form("06:00"),
                  enabled: str = Form("off")):
    _require_auth(request)
    cfg = load_config()
    for cam in cfg.cameras:
        if cam.get("id") == cam_id:
            schedule = cam.setdefault("pause_schedule", [])
            next_id = max((p.get("id", 0) for p in schedule), default=0) + 1
            schedule.append({
                "id": next_id, "label": label, "day": day,
                "start": start, "end": end, "enabled": enabled == "on",
            })
            break
    save_config(cfg)
    return RedirectResponse("/cameras", status_code=302)


@app.post("/cameras/{cam_id}/pause/{period_id}/toggle")
def toggle_cam_pause(request: Request, cam_id: int, period_id: int):
    _require_auth(request)
    cfg = load_config()
    for cam in cfg.cameras:
        if cam.get("id") == cam_id:
            for p in cam.get("pause_schedule", []):
                if p.get("id") == period_id:
                    p["enabled"] = not p.get("enabled", True)
                    break
            break
    save_config(cfg)
    return RedirectResponse("/cameras", status_code=302)


@app.post("/cameras/{cam_id}/pause/{period_id}/delete")
def delete_cam_pause(request: Request, cam_id: int, period_id: int):
    _require_auth(request)
    cfg = load_config()
    for cam in cfg.cameras:
        if cam.get("id") == cam_id:
            cam["pause_schedule"] = [p for p in cam.get("pause_schedule", []) if p.get("id") != period_id]
            break
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


# ── Public API (no auth) ──────────────────────────────────────────────────────

@app.get("/api/cameras")
def api_cameras():
    """Public endpoint — returns camera list with computed public image URLs."""
    cfg = load_config()
    base = cfg.upload.public_base_url.rstrip("/")
    result = []
    for cam in cfg.cameras:
        filename = cam.get("filename", "")
        result.append({
            "id":         cam.get("id"),
            "name":       cam.get("name", ""),
            "filename":   filename,
            "public_url": f"{base}/{filename}" if base and filename else "",
        })
    return JSONResponse(result)


# ── Upload settings ───────────────────────────────────────────────────────────

@app.get("/upload")
def upload_page(request: Request):
    _require_auth(request)
    cfg = load_config()
    return templates.TemplateResponse("upload.html", {"request": request, "cfg": cfg, "cameras": cfg.cameras})


@app.post("/upload")
def save_upload(request: Request,
                method: str = Form(...),
                public_base_url: str = Form(""),
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
    cfg.upload.public_base_url    = public_base_url.strip()
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


# ── System settings (timezone + allowed hosts) ────────────────────────────────

@app.get("/settings")
def settings_page(request: Request):
    _require_auth(request)
    cfg = load_config()
    return templates.TemplateResponse("settings.html", {"request": request, "cfg": cfg})


@app.post("/settings")
def save_settings(request: Request,
                  timezone: str = Form("Europe/Copenhagen"),
                  allowed_hosts: str = Form("*")):
    _require_auth(request)
    cfg = load_config()
    cfg.timezone = timezone.strip() or "Europe/Copenhagen"
    hosts = [h.strip() for h in allowed_hosts.splitlines() if h.strip()]
    cfg.allowed_hosts = hosts if hosts else ["*"]
    save_config(cfg)
    logger.info("Systemindstillinger gemt. Genstart tjenesten for at anvende ændrede tilladte hosts.")
    return RedirectResponse("/settings", status_code=302)


# ── Backup / Restore ──────────────────────────────────────────────────────────

@app.get("/backup")
def backup_page(request: Request):
    _require_auth(request)
    return templates.TemplateResponse("backup.html", {"request": request})


@app.get("/backup/download")
def backup_download(request: Request, strip_auth: int = Query(0)):
    _require_auth(request)
    cfg = load_config()
    if strip_auth:
        xml_bytes = config_to_xml_no_auth(cfg)
        filename = datetime.now().strftime("backup_no_auth_%Y%m%d_%H%M%S.xml")
    else:
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

def _should_fire(cam_id: int, interval_minutes: int) -> bool:
    """True if enough time has elapsed for this camera to take a new snapshot."""
    now = time.monotonic()
    next_fire = _cam_next_fire.get(cam_id, 0)
    if now >= next_fire:
        _cam_next_fire[cam_id] = now + interval_minutes * 60
        return True
    return False


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

            tz = cfg.timezone or "Europe/Copenhagen"

            for cam in cfg.cameras:
                if not cam.get("enabled"):
                    continue
                rtsp = cam.get("rtsp_url", "")
                if not rtsp:
                    continue
                cam_id = cam.get("id", 0)
                interval = max(1, cam.get("capture_interval_minutes", cfg.capture_interval_minutes))

                if not _should_fire(cam_id, interval):
                    continue

                # Per-camera pause schedule (falls back to global dark_periods)
                cam_schedule = cam.get("pause_schedule") or cfg.dark_periods
                dark, reason = is_dark_time(cam_schedule, tz)
                if dark:
                    logger.info("Kamera '%s' pauseret (%s).", cam.get("name"), reason)
                    continue

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
            # Poll every 30 seconds; individual camera timers control actual fire rate
            threading.Event().wait(30)
