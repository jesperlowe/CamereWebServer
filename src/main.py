import asyncio
import logging
import threading
from collections import deque
from datetime import datetime, timezone

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeSerializer

from src.capture import capture_snapshot
from src.config import hash_password, load_config, save_config, verify_password
from src.uploader import upload_image

app = FastAPI(title="Camera Uploader")
app.mount("/static", StaticFiles(directory="src/static"), name="static")
templates = Jinja2Templates(directory="src/templates")
secret = URLSafeSerializer("camera-uploader-secret")

logger = logging.getLogger("camera_uploader")
logging.basicConfig(level=logging.INFO)
log_buffer = deque(maxlen=100)

state = {"last_upload": None, "last_error": "-", "last_test_image": b""}


class BufferHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        log_buffer.appendleft(msg)


logger.addHandler(BufferHandler())


def _authed(request: Request):
    token = request.cookies.get("session")
    if not token:
        return False
    try:
        return bool(secret.loads(token).get("u"))
    except Exception:
        return False


def _require_auth(request: Request):
    if not _authed(request):
        raise HTTPException(status_code=302, headers={"Location": "/login"})


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    cfg = load_config()
    if username != cfg.auth.username or not verify_password(password, cfg.auth.password_hash):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Forkert login"})
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie("session", secret.dumps({"u": username}), httponly=True)
    return resp


@app.get("/")
def dashboard(request: Request):
    _require_auth(request)
    cfg = load_config()
    return templates.TemplateResponse("dashboard.html", {"request": request, "state": state, "force": cfg.auth.force_password_change})


@app.get("/camera")
def camera_page(request: Request):
    _require_auth(request)
    cfg = load_config()
    return templates.TemplateResponse("camera.html", {"request": request, "cfg": cfg})


@app.post("/camera")
def save_camera(request: Request, rtsp_url: str = Form(...), interval: int = Form(...)):
    _require_auth(request)
    cfg = load_config()
    cfg.camera.rtsp_url = rtsp_url
    cfg.camera.capture_interval_minutes = interval
    save_config(cfg)
    return RedirectResponse("/camera", status_code=302)


@app.get("/upload")
def upload_page(request: Request):
    _require_auth(request)
    return templates.TemplateResponse("upload.html", {"request": request, "cfg": load_config()})


@app.post("/upload")
def save_upload(request: Request, method: str = Form(...), sftp_host: str = Form(""), sftp_port: int = Form(22), sftp_username: str = Form(""), sftp_password: str = Form(""), sftp_key: str = Form(""), sftp_remote_path: str = Form(""), wp_endpoint: str = Form(""), wp_token: str = Form("")):
    _require_auth(request)
    cfg = load_config()
    cfg.upload.method = method
    cfg.upload.sftp.host = sftp_host
    cfg.upload.sftp.port = sftp_port
    cfg.upload.sftp.username = sftp_username
    if sftp_password:
        cfg.upload.sftp.password = sftp_password
    cfg.upload.sftp.private_key_path = sftp_key
    cfg.upload.sftp.remote_path = sftp_remote_path
    cfg.upload.wordpress.endpoint = wp_endpoint
    if wp_token:
        cfg.upload.wordpress.bearer_token = wp_token
    save_config(cfg)
    return RedirectResponse("/upload", status_code=302)


@app.post("/test-camera")
def test_camera(request: Request):
    _require_auth(request)
    cfg = load_config()
    img = capture_snapshot(cfg.camera.rtsp_url)
    state["last_test_image"] = img
    return RedirectResponse("/", status_code=302)


@app.post("/upload-test")
def upload_test(request: Request):
    _require_auth(request)
    cfg = load_config()
    img = state["last_test_image"] or capture_snapshot(cfg.camera.rtsp_url)
    upload_image(img, cfg)
    state["last_upload"] = datetime.now(timezone.utc).isoformat()
    return RedirectResponse("/", status_code=302)


@app.get("/test-image")
def test_image(request: Request):
    _require_auth(request)
    return Response(content=state["last_test_image"], media_type="image/jpeg")


@app.get("/logs")
def logs_page(request: Request):
    _require_auth(request)
    return templates.TemplateResponse("logs.html", {"request": request, "logs": list(log_buffer)})


@app.post("/change-password")
def change_password(request: Request, password: str = Form(...)):
    _require_auth(request)
    cfg = load_config()
    cfg.auth.password_hash = hash_password(password)
    cfg.auth.force_password_change = False
    save_config(cfg)
    return RedirectResponse("/", status_code=302)


def scheduler_loop():
    while True:
        try:
            cfg = load_config()
            if cfg.camera.rtsp_url:
                img = capture_snapshot(cfg.camera.rtsp_url)
                upload_image(img, cfg)
                state["last_upload"] = datetime.now(timezone.utc).isoformat()
                state["last_error"] = "-"
        except Exception as exc:
            logger.error("Scheduler fejl: %s", exc)
            state["last_error"] = str(exc)
        finally:
            interval = max(load_config().camera.capture_interval_minutes, 1)
            threading.Event().wait(interval * 60)


@app.on_event("startup")
async def startup_event():
    threading.Thread(target=scheduler_loop, daemon=True).start()

