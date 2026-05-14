"""
Network utilities: read interface IPs, read/write hostname, read/write
static IP config via /etc/dhcpcd.conf (Raspberry Pi OS).

All write operations require root. Call has_root_permission() first;
if it returns False, offer read-only display and disable save buttons.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DHCPCD_CONF = Path("/etc/dhcpcd.conf")
HOSTNAME_FILE = Path("/etc/hostname")
HOSTS_FILE = Path("/etc/hosts")

# Interfaces treated as WiFi / wired by prefix
_WIFI_PREFIXES = ("wlan",)
_ETH_PREFIXES  = ("eth", "en")


def has_root_permission() -> bool:
    return os.geteuid() == 0


# ── Hostname ──────────────────────────────────────────────────────────────────

def get_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        try:
            return HOSTNAME_FILE.read_text().strip()
        except Exception:
            return "unknown"


def set_hostname(new_hostname: str) -> None:
    """
    Update /etc/hostname and /etc/hosts, then apply with `hostname` command.
    Raises ValueError for invalid names, PermissionError if not root.
    """
    if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$', new_hostname):
        raise ValueError(f"Invalid hostname: {new_hostname!r}")

    old = get_hostname()

    HOSTNAME_FILE.write_text(new_hostname + "\n")

    # Update /etc/hosts: replace occurrences of old hostname
    if HOSTS_FILE.exists():
        text = HOSTS_FILE.read_text()
        text = re.sub(
            r'\b' + re.escape(old) + r'\b',
            new_hostname,
            text,
        )
        HOSTS_FILE.write_text(text)

    # Apply immediately
    subprocess.run(["hostname", new_hostname], check=True)
    logger.info("Hostname ændret fra '%s' til '%s'", old, new_hostname)


# ── Network interfaces ────────────────────────────────────────────────────────

def _iface_type(name: str) -> str:
    if any(name.startswith(p) for p in _WIFI_PREFIXES):
        return "wifi"
    if any(name.startswith(p) for p in _ETH_PREFIXES):
        return "eth"
    return "other"


def _read_interfaces_ip() -> list[dict]:
    """
    Parse `ip -o addr show` output.  Returns list of:
      {name, type, ip, prefix_len, mac, state}
    """
    interfaces: dict[str, dict] = {}
    try:
        out = subprocess.check_output(
            ["ip", "-o", "addr", "show"], text=True, stderr=subprocess.DEVNULL
        )
        for line in out.splitlines():
            # Format: <idx>: <iface>    <af> <addr>/<prefix> ...
            m = re.match(r'^\d+:\s+(\S+)\s+(inet)\s+([\d.]+)/(\d+)', line)
            if not m:
                continue
            name, _, ip, prefix = m.groups()
            if name == "lo":
                continue
            if name not in interfaces:
                interfaces[name] = {
                    "name":       name,
                    "type":       _iface_type(name),
                    "ip":         "",
                    "prefix_len": "",
                    "mac":        "",
                    "state":      "down",
                }
            interfaces[name]["ip"] = ip
            interfaces[name]["prefix_len"] = prefix
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning("ip addr: %s", exc)

    # Fill MAC addresses and state
    try:
        link_out = subprocess.check_output(
            ["ip", "-o", "link", "show"], text=True, stderr=subprocess.DEVNULL
        )
        for line in link_out.splitlines():
            m_name  = re.search(r'^\d+:\s+(\S+):', line)
            m_mac   = re.search(r'link/ether\s+([\da-f:]+)', line)
            m_state = re.search(r'\bstate\s+(\S+)', line)
            if not m_name:
                continue
            name = m_name.group(1).split("@")[0]  # strip @physical
            if name == "lo" or name not in interfaces:
                continue
            if m_mac:
                interfaces[name]["mac"] = m_mac.group(1)
            if m_state:
                s = m_state.group(1).lower()
                interfaces[name]["state"] = "up" if s in ("up", "unknown") else "down"
    except Exception as exc:
        logger.warning("ip link: %s", exc)

    # Ensure common interfaces appear even if not connected
    for iface in ("eth0", "wlan0"):
        if iface not in interfaces:
            interfaces[iface] = {
                "name": iface, "type": _iface_type(iface),
                "ip": "", "prefix_len": "", "mac": "", "state": "down",
            }

    # Sort: eth first, then wlan, then others
    order = {"eth": 0, "wifi": 1, "other": 2}
    return sorted(interfaces.values(), key=lambda x: (order.get(x["type"], 2), x["name"]))


def get_interfaces() -> list[dict]:
    return _read_interfaces_ip()


# ── dhcpcd.conf static IP ────────────────────────────────────────────────────

def _prefix_to_netmask(prefix: str) -> str:
    """Convert CIDR prefix length to dotted netmask."""
    try:
        n = int(prefix)
        mask = (0xFFFFFFFF >> (32 - n)) << (32 - n)
        return ".".join(str((mask >> (8 * i)) & 0xFF) for i in reversed(range(4)))
    except Exception:
        return ""


def read_dhcpcd_config(iface: str) -> dict:
    """
    Parse the static IP block for *iface* from /etc/dhcpcd.conf.
    Returns: {mode: 'dhcp'|'static', address, netmask, gateway, dns}
    """
    result = {"mode": "dhcp", "address": "", "netmask": "", "gateway": "", "dns": ""}
    if not DHCPCD_CONF.exists():
        return result

    text = DHCPCD_CONF.read_text()
    # Find the interface block
    pattern = re.compile(
        r'interface\s+' + re.escape(iface) + r'\s*\n(.*?)(?=\ninterface\s|\Z)',
        re.DOTALL,
    )
    m = pattern.search(text)
    if not m:
        return result

    block = m.group(1)
    if "static ip_address" in block:
        result["mode"] = "static"
        ip_m = re.search(r'static ip_address=([\d.]+)/(\d+)', block)
        if ip_m:
            result["address"] = ip_m.group(1)
            result["netmask"] = _prefix_to_netmask(ip_m.group(2))
        gw_m = re.search(r'static routers=([\d.]+)', block)
        if gw_m:
            result["gateway"] = gw_m.group(1)
        dns_m = re.search(r'static domain_name_servers=([\d.]+)', block)
        if dns_m:
            result["dns"] = dns_m.group(1)
    return result


def _netmask_to_prefix(netmask: str) -> int:
    """Convert dotted netmask to CIDR prefix length."""
    try:
        parts = list(map(int, netmask.split(".")))
        n = sum(bin(p).count("1") for p in parts)
        return n
    except Exception:
        return 24


def write_dhcpcd_config(iface: str, mode: str,
                        address: str = "", netmask: str = "",
                        gateway: str = "", dns: str = "") -> None:
    """
    Write (or remove) the static IP block for *iface* in /etc/dhcpcd.conf.
    Creates the file if it does not exist.
    """
    original = DHCPCD_CONF.read_text() if DHCPCD_CONF.exists() else ""

    # Remove any existing block for this interface
    pattern = re.compile(
        r'\ninterface\s+' + re.escape(iface) + r'\s*\n.*?(?=\ninterface\s|\Z)',
        re.DOTALL,
    )
    cleaned = pattern.sub("", original).rstrip()

    if mode == "static":
        prefix = _netmask_to_prefix(netmask) if netmask else 24
        block = (
            f"\ninterface {iface}\n"
            f"static ip_address={address}/{prefix}\n"
        )
        if gateway:
            block += f"static routers={gateway}\n"
        if dns:
            block += f"static domain_name_servers={dns}\n"
        new_text = cleaned + "\n" + block
    else:
        new_text = cleaned + "\n"

    DHCPCD_CONF.write_text(new_text)
    logger.info("dhcpcd.conf opdateret for %s (mode=%s)", iface, mode)
