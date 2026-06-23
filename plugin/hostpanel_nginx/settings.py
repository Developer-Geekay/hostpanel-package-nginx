"""
Nginx plugin settings — stored in the shared HostPanel SQLite DB.
Key-value store for nginx configuration directives. Settings are applied
by regenerating nginx.conf and all cpanel vhosts, then reloading nginx.
"""
import logging
import os
import re
import subprocess
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import User
from db import get_conn
from deps import require_admin
from modules.audit.logger import log_action

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cpanelapi/nginx/settings", tags=["Nginx Settings"])

NGINX_DIR = "/opt/hostpanel/plugins/nginx"
NGINX_BIN = f"{NGINX_DIR}/nginx"

DEFAULTS: dict[str, str] = {
    "client_max_body_size": "50m",
    "keepalive_timeout":    "65",
    "worker_connections":   "1024",
    "proxy_read_timeout":   "86400",
}


def _ensure_table() -> None:
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nginx_settings (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )
        """)


def get_settings() -> dict[str, str]:
    _ensure_table()
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM nginx_settings").fetchall()
    stored = {r["key"]: r["value"] for r in rows}
    return {**DEFAULTS, **stored}


def save_settings(data: dict[str, str]) -> None:
    _ensure_table()
    with get_conn() as conn:
        for key, value in data.items():
            conn.execute(
                """INSERT INTO nginx_settings (key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE
                   SET value=excluded.value,
                       updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
                (key, value),
            )


def generate_nginx_conf(settings: dict[str, str]) -> str:
    return f"""user root;
worker_processes 1;

events {{
    worker_connections {settings['worker_connections']};
}}

http {{
    include       /opt/hostpanel/plugins/nginx/mime.types;
    default_type  application/octet-stream;

    client_body_temp_path /opt/hostpanel/plugins/nginx/client_body_temp;
    proxy_temp_path       /opt/hostpanel/plugins/nginx/proxy_temp;
    fastcgi_temp_path     /opt/hostpanel/plugins/nginx/fastcgi_temp;
    uwsgi_temp_path       /opt/hostpanel/plugins/nginx/uwsgi_temp;
    scgi_temp_path        /opt/hostpanel/plugins/nginx/scgi_temp;

    sendfile        on;
    keepalive_timeout {settings['keepalive_timeout']};
    client_max_body_size {settings['client_max_body_size']};

    client_header_buffer_size  8k;
    large_client_header_buffers 4 32k;

    include /opt/hostpanel/plugins/nginx/vhosts/*.conf;

    server {{
        listen 80 default_server;
        listen [::]:80 default_server;
        server_name _;
        return 444;
    }}
}}
"""


def apply_settings(settings: dict[str, str]) -> None:
    """Write nginx.conf from settings, regenerate all cpanel vhosts, reload nginx."""
    conf_path = os.path.join(NGINX_DIR, "nginx.conf")
    result = subprocess.run(
        ["sudo", "tee", conf_path],
        input=generate_nginx_conf(settings), text=True, capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to write nginx.conf: {result.stderr}")
    subprocess.run(["sudo", "chmod", "644", conf_path], capture_output=True)

    try:
        import glob
        from hostpanel_nginx.domains import write_nginx_cpanel_vhost, VHOSTS_DIR
        from domain_registry import _load_domains

        processed = set()

        for domain_rec in _load_domains():
            domain_name = domain_rec["domain_name"]
            doc_root = domain_rec.get("document_root", "")
            cpanel_vhost = os.path.join(VHOSTS_DIR, f"cpanel.{domain_name}.conf")
            https_forced = False
            cert_path = key_path = ""
            if os.path.exists(cpanel_vhost):
                with open(cpanel_vhost) as fv:
                    content = fv.read()
                https_forced = " ssl;" in content
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("ssl_certificate ") and "_key" not in stripped:
                        cert_path = stripped.split()[-1].rstrip(";")
                    elif stripped.startswith("ssl_certificate_key "):
                        key_path = stripped.split()[-1].rstrip(";")
            write_nginx_cpanel_vhost(
                domain_name, doc_root,
                https_forced=https_forced,
                cert_path=cert_path, key_path=key_path,
                settings=settings, skip_reload=True,
            )
            processed.add(domain_name)

        # Also regenerate any cpanel vhosts that exist on disk but whose domain
        # is not in the registry (e.g. the panel's own cpanel.<server-domain>.conf).
        for vhost_file in glob.glob(os.path.join(VHOSTS_DIR, "cpanel.*.conf")):
            fname = os.path.basename(vhost_file)
            domain_name = fname[len("cpanel."):-len(".conf")]
            if domain_name in processed:
                continue
            https_forced = False
            cert_path = key_path = ""
            with open(vhost_file) as fv:
                content = fv.read()
            https_forced = " ssl;" in content
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("ssl_certificate ") and "_key" not in stripped:
                    cert_path = stripped.split()[-1].rstrip(";")
                elif stripped.startswith("ssl_certificate_key "):
                    key_path = stripped.split()[-1].rstrip(";")
            write_nginx_cpanel_vhost(
                domain_name, "",
                https_forced=https_forced,
                cert_path=cert_path, key_path=key_path,
                settings=settings, skip_reload=True,
            )
            logger.info(f"nginx settings: regenerated orphan cpanel vhost for {domain_name}")

    except Exception as e:
        logger.warning(f"nginx settings: could not regenerate cpanel vhosts: {e}")

    subprocess.run(
        [NGINX_BIN, "-p", NGINX_DIR, "-s", "reload"],
        capture_output=True,
    )
    logger.info("Nginx settings applied and nginx reloaded")


class NginxSettingsUpdate(BaseModel):
    client_max_body_size: Optional[str] = None
    keepalive_timeout:    Optional[str] = None
    worker_connections:   Optional[str] = None
    proxy_read_timeout:   Optional[str] = None


def _validate_settings(data: dict) -> None:
    body_size = data.get("client_max_body_size")
    if body_size is not None and not re.fullmatch(r'\d+[kmgKMG]?', body_size):
        raise HTTPException(status_code=422, detail="client_max_body_size must be a number optionally followed by k, m, or g (e.g. 50m)")
    for field in ("keepalive_timeout", "proxy_read_timeout", "worker_connections"):
        val = data.get(field)
        if val is not None and (not val.isdigit() or int(val) <= 0):
            raise HTTPException(status_code=422, detail=f"{field} must be a positive integer")


@router.get("")
async def get_nginx_settings(_: User = Depends(require_admin)):
    return {"status": "success", "settings": get_settings()}


@router.put("")
async def update_nginx_settings(
    body: NginxSettingsUpdate,
    current_user: User = Depends(require_admin),
):
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        return {"status": "success", "message": "Nothing to update"}
    _validate_settings(updates)
    if "client_max_body_size" in updates:
        updates["client_max_body_size"] = updates["client_max_body_size"].lower()
    try:
        merged = {**get_settings(), **updates}
        save_settings(updates)
        apply_settings(merged)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    log_action(current_user.username, "nginx.settings_update", "nginx_settings", str(updates))
    return {"status": "success", "settings": merged, "message": "Settings saved and nginx reloaded"}
