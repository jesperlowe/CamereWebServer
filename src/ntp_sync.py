import logging
from datetime import datetime, timezone

logger = logging.getLogger("camera_uploader")


def check_ntp(server: str) -> dict:
    try:
        import ntplib
        c = ntplib.NTPClient()
        resp = c.request(server, version=3, timeout=5)
        return {
            "ok": True,
            "offset_sec": round(resp.offset, 3),
            "server": server,
            "server_time": datetime.fromtimestamp(resp.tx_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
    except Exception as exc:
        logger.warning("NTP-forespørgsel fejlede (%s): %s", server, exc)
        return {"ok": False, "error": str(exc), "server": server}
