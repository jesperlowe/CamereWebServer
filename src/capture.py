import logging
import subprocess

logger = logging.getLogger("camera_uploader")


def capture_snapshot(rtsp_url: str, timeout_sec: int = 20) -> bytes:
    if not rtsp_url:
        raise ValueError("RTSP URL er ikke konfigureret.")
    cmd = [
        "ffmpeg",
        "-loglevel", "warning",
        "-rtsp_transport", "tcp",
        # Skip audio negotiation; older cameras sometimes reject the session
        # when ffmpeg tries to set up both video and audio tracks.
        "-allowed_media_types", "video",
        "-i", rtsp_url,
        "-frames:v", "1",
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "pipe:1",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout_sec, check=False)
    except subprocess.TimeoutExpired as exc:
        logger.error("Timeout ved capture fra kamera.")
        raise RuntimeError("Timeout ved hentning af billede fra kamera.") from exc

    if proc.returncode != 0 or not proc.stdout:
        stderr_snippet = proc.stderr.decode(errors="replace").strip()[-400:]
        logger.error(
            "ffmpeg fejl ved capture (kode=%s).\n%s",
            proc.returncode,
            stderr_snippet,
        )
        raise RuntimeError("Kunne ikke hente billede fra stream. Kontrollér RTSP URL og login.")
    return proc.stdout
