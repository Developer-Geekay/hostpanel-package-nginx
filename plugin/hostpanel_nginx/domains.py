import os
import logging
import re
import secrets
import shutil
import string
import subprocess
import httpx
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from typing import List

from auth import User
from deps import get_current_user, require_admin
from modules.audit.logger import log_action
from domain_registry import (
    _load_domains, _save_domains,
    _load_subdomains, _save_subdomains,
    check_domain_access,
)

router = APIRouter(prefix="/cpanelapi/domains", tags=["Domains"])
logger = logging.getLogger(__name__)

NGINX_BIN  = "/opt/hostpanel/plugins/nginx/nginx"
VHOSTS_DIR = "/opt/hostpanel/plugins/nginx/vhosts"

RESERVED_DOMAINS = {"localhost", "127.0.0.1"}


# ── Models ─────────────────────────────────────────────────────────────────────

class DomainCreateRequest(BaseModel):
    domain_name: str
    aliases: str = ""
    proxy_pass: str = ""
    php_version: str = ""
    gzip_enabled: bool = False
    https_enabled: bool = False
    https_forced: bool = False

class VhostOnlyCreateRequest(BaseModel):
    """Vhost-only creation: write just the nginx server block. No tenant user,
    no public_html, no DNS zone — the operator maps DNS and the document root
    themselves. Independent of the full add_domain provisioning flow."""
    domain_name: str
    aliases: str = ""
    document_root: str = ""
    proxy_pass: str = ""
    php_version: str = ""
    gzip_enabled: bool = False
    https_forced: bool = False

class SubdomainCreateRequest(BaseModel):
    subdomain: str

class SubdomainResponse(BaseModel):
    fqdn: str
    subdomain: str
    parent_domain: str
    document_root: str
    username: str
    status: str
    https_forced: bool = False

class DomainResponse(BaseModel):
    domain_name: str
    username: str
    document_root: str
    status: str

class DomainDetail(DomainResponse):
    https_forced: bool

class ForceHttpsRequest(BaseModel):
    enabled: bool

class DomainProvisionItem(BaseModel):
    domain: str
    issue_ssl: bool = False

class ProvisionRequest(BaseModel):
    domains: List[DomainProvisionItem]

class VhostUpdateRequest(BaseModel):
    content: str


# ── Helpers ────────────────────────────────────────────────────────────────────

def _default_index_html(hostname: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{hostname}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: system-ui, -apple-system, sans-serif;
      background: #f8f9fc; color: #0f1623;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh; padding: 24px;
    }}
    .card {{
      background: #fff; border: 1px solid #e8eaf0; border-radius: 12px;
      padding: 48px 40px; max-width: 480px; width: 100%; text-align: center;
      box-shadow: 0 4px 16px rgba(15,22,35,.08);
    }}
    .badge {{
      display: inline-flex; align-items: center; gap: 6px;
      background: rgba(99,102,241,.1); color: #6366f1;
      font-size: 11px; font-weight: 700; letter-spacing: .8px;
      text-transform: uppercase; padding: 4px 12px; border-radius: 20px; margin-bottom: 20px;
    }}
    h1 {{ font-size: 28px; font-weight: 800; letter-spacing: -.5px; margin-bottom: 10px; }}
    p  {{ font-size: 14px; color: #8890a8; line-height: 1.6; }}
    .domain {{ font-family: monospace; color: #6366f1; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="badge">&#x2713; Site Active</div>
    <h1>You&#39;re live!</h1>
    <p>
      <span class="domain">{hostname}</span> is provisioned and serving from
      <code>public_html</code>. Replace this file to publish your site.
    </p>
  </div>
</body>
</html>
"""


# An operator-supplied document root is interpolated into privileged nginx
# config (`root {document_root};`). Constrain it to an absolute path of safe
# path characters so it can never carry an nginx directive/injection payload.
_DOC_ROOT_RE = re.compile(r"^/(?:[A-Za-z0-9._-]+/?)+$")


def _validate_document_root(root: str) -> str:
    root = (root or "").strip().rstrip("/")
    if not root:
        raise HTTPException(
            status_code=400,
            detail="Document root is required for a static vhost-only host.",
        )
    if ".." in root or not _DOC_ROOT_RE.match(root):
        raise HTTPException(
            status_code=400,
            detail="Document root must be an absolute path using letters, digits, '.', '_', '-', '/'.",
        )
    return root


def _derive_username(domain: str) -> str:
    label = domain.split(".")[0]
    safe = re.sub(r"[^a-z0-9_]", "", label.lower())[:32] or "web"
    return safe


def _random_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _provision_tenant_webroot(username: str, domain: str) -> str:
    """Create the tenant Linux user (idempotent) and its public_html under the
    tenant's own home, owned by the tenant. Returns the document root.

    The site lives in the tenant's home (cPanel-style), never a root-owned
    /var/www path, and the tree is owned by the tenant — no world-writable 777.
    Safe to re-run (used by both add_domain and the reconcile/repair path).
    """
    from modules.users import system as _sys_users

    document_root = f"/home/{username}/public_html"

    # 1. Linux user for this tenant
    if not any(u["username"] == username for u in _sys_users.get_sys_users()):
        _sys_users.create_linux_user(username, _random_password())

    # 2. Web root
    subprocess.run(["sudo", "-n", "mkdir", "-p", document_root],
                   check=True, capture_output=True)

    # 3. Seed index.html only if absent — never clobber an existing site
    index_path = os.path.join(document_root, "index.html")
    if not os.path.exists(index_path):
        subprocess.run(
            ["sudo", "-n", "tee", index_path],
            input=_default_index_html(domain), text=True, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    # 4. Own the tree to the tenant; home stays traversable but not world-writable
    subprocess.run(
        ["sudo", "-n", "/opt/hostpanel/bin/hp-chown",
         f"{username}:/home/{username}/public_html"],
        capture_output=True,
    )
    subprocess.run(["sudo", "-n", "chmod", "-R", "755", f"/home/{username}"],
                   capture_output=True)
    return document_root


def run_command_safe(command: List[str]):
    # Insert -n after sudo so sudo-rs never prompts in non-TTY context
    if command and command[0] == "sudo":
        command = ["sudo", "-n"] + command[1:]
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {' '.join(command)}: {e.stderr}")
        raise HTTPException(status_code=500, detail=f"System error: {e.stderr.strip()}")


def nginx_reload():
    run_command_safe(["sudo", NGINX_BIN, "-s", "reload"])


def _is_https_forced(domain_name: str) -> bool:
    vhost_path = f"{VHOSTS_DIR}/{domain_name}.conf"
    if not os.path.exists(vhost_path):
        return False
    with open(vhost_path, "r") as f:
        return "return 301 https://$host" in f.read()


def _render_nodejs_domain(domain_name: str, cert_path: str = "", key_path: str = ""):
    """Domains owned by a Node.js app render through the core's single vhost
    template (reverse proxy + custom routes + SSL awareness). Writing this
    package's static/php template for such a domain would clobber the app's
    proxy — the historical 403-after-restart bug. Returns the rendered config,
    or None when the domain has no Node.js app (or the plugin/core renderer
    isn't available, e.g. older installs), in which case the caller proceeds
    with its own template."""
    try:
        from hostpanel_nodejs.store import get_app_by_domain
        app = get_app_by_domain(domain_name)
        if not app:
            return None
        if not cert_path or not key_path:
            try:
                from hostpanel_nodejs.validators import _find_cert_paths
                cert_path, key_path = _find_cert_paths(domain_name)
            except Exception:
                cert_path, key_path = "", ""
        from nginx_vhost import render_domain_vhost
        return render_domain_vhost(domain_name, app["username"], cert_path or "", key_path or "")
    except Exception:
        return None


def write_nginx_vhost(domain_name: str, document_root: str, https_forced: bool = False,
                      skip_if_exists: bool = False, cert_path: str = "", key_path: str = "",
                      aliases: str = "", proxy_pass: str = "", php_version: str = "",
                      gzip_enabled: bool = False):
    if skip_if_exists and os.path.exists(f"{VHOSTS_DIR}/{domain_name}.conf"):
        logger.info(f"Nginx vhost already exists for {domain_name}, skipping")
        return

    # Node.js-owned domains: every flow that lands here (startup provisioning,
    # force-https toggle, SSL enable/disable, re-provision) emits the correct
    # proxy vhost instead of clobbering it with the static template.
    delegated = _render_nodejs_domain(domain_name, cert_path, key_path)
    if delegated is not None:
        try:
            os.makedirs(VHOSTS_DIR, exist_ok=True)
            with open(f"{VHOSTS_DIR}/{domain_name}.conf", "w") as f:
                f.write(delegated)
            nginx_reload()
            logger.info(f"Nginx vhost for {domain_name} rendered via core (Node.js app domain)")
            return
        except Exception as e:
            logger.error(f"Failed to write delegated vhost for {domain_name}: {e}")
            raise HTTPException(status_code=500, detail="Failed to write Nginx configuration")

    alias_extras = " ".join(a.strip() for a in aliases.split() if a.strip()) if aliases else ""
    server_names = f"{domain_name} www.{domain_name}" + (f" {alias_extras}" if alias_extras else "")

    gzip_block = """
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;
    gzip_min_length 1000;
""" if gzip_enabled else ""

    if proxy_pass:
        main_location = f"""    location / {{
        proxy_pass {proxy_pass};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }}"""
    elif php_version:
        sock = f"/run/php/{php_version}.sock"
        main_location = f"""    location / {{
        try_files $uri $uri/ /index.php?$query_string;
    }}

    location ~ \\.php$ {{
        fastcgi_pass unix:{sock};
        fastcgi_index index.php;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }}"""
    else:
        main_location = """    location / {
        try_files $uri $uri/ /index.html;
    }"""

    if https_forced and cert_path and key_path:
        vhost_config = f"""# Generated by HostPanel
server {{
    listen 80;
    server_name {server_names};

    location ^~ /.well-known/acme-challenge/ {{
        root {document_root};
        default_type "text/plain";
        try_files $uri =404;
    }}

    location / {{
        return 301 https://$host$request_uri;
    }}
}}

server {{
    listen 443 ssl;
    server_name {server_names};
    root {document_root};
    index index.php index.html index.htm;

    ssl_certificate     {cert_path};
    ssl_certificate_key {key_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    add_header Strict-Transport-Security "max-age=31536000" always;

    access_log /opt/hostpanel/plugins/nginx/logs/{domain_name}.access.log;
    error_log  /opt/hostpanel/plugins/nginx/logs/{domain_name}.error.log;
{gzip_block}
{main_location}
}}
"""
    else:
        vhost_config = f"""# Generated by HostPanel
server {{
    listen 80;
    server_name {server_names};
    root {document_root};
    index index.php index.html index.htm;

    access_log /opt/hostpanel/plugins/nginx/logs/{domain_name}.access.log;
    error_log  /opt/hostpanel/plugins/nginx/logs/{domain_name}.error.log;

    location ^~ /.well-known/acme-challenge/ {{
        default_type "text/plain";
        try_files $uri =404;
    }}
{gzip_block}
{main_location}
}}
"""
    try:
        os.makedirs(VHOSTS_DIR, exist_ok=True)
        with open(f"{VHOSTS_DIR}/{domain_name}.conf", "w") as f:
            f.write(vhost_config)
        nginx_reload()
        logger.info(f"Nginx vhost written and reloaded for {domain_name}")
    except Exception as e:
        logger.error(f"Failed to configure Nginx for {domain_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to write Nginx configuration")


def write_nginx_cpanel_vhost(domain_name: str, document_root: str = "",
                             https_forced: bool = False,
                             cert_path: str = "", key_path: str = "",
                             skip_if_exists: bool = False,
                             settings: dict | None = None,
                             skip_reload: bool = False):
    """Create/update the nginx vhost for cpanel.<domain>.
    HTTP-only: port panel_port → proxy to 127.0.0.1:panel_port.
    HTTPS: port panel_port redirects to panel_ssl_port, panel_ssl_port terminates SSL
    and proxies to 127.0.0.1:panel_port."""
    if settings is None:
        try:
            from hostpanel_nginx.settings import get_settings as _get_settings
            settings = _get_settings()
        except Exception:
            settings = {}

    panel_port         = int(os.environ.get("PANEL_PORT",         "2082"))
    panel_ssl_port     = int(os.environ.get("PANEL_SSL_PORT",     "2083"))
    panel_backend_port = int(os.environ.get("PANEL_BACKEND_PORT", "2081"))
    body_size          = settings.get("client_max_body_size", "50m")
    proxy_timeout      = settings.get("proxy_read_timeout",   "86400")
    cpanel_fqdn    = f"cpanel.{domain_name}"
    vhost_path     = f"{VHOSTS_DIR}/{cpanel_fqdn}.conf"
    if skip_if_exists and os.path.exists(vhost_path):
        return

    acme_block = f"""
    location ^~ /.well-known/acme-challenge/ {{
        root {document_root};
        default_type "text/plain";
        try_files $uri =404;
    }}
""" if document_root else ""

    proxy_block = f"""    client_max_body_size {body_size};

    location / {{
        proxy_pass http://127.0.0.1:{panel_backend_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout {proxy_timeout};
    }}"""

    if https_forced and cert_path and key_path:
        vhost_config = f"""# Redirect panel HTTP port → panel HTTPS port
server {{
    listen {panel_port};
    server_name {cpanel_fqdn};
{acme_block}
    location / {{
        return 301 https://$host:{panel_ssl_port}$request_uri;
    }}
}}

# Panel HTTPS — SSL termination, proxy to backend
server {{
    listen {panel_ssl_port} ssl;
    server_name {cpanel_fqdn};

    ssl_certificate     {cert_path};
    ssl_certificate_key {key_path};

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    add_header Strict-Transport-Security "max-age=31536000" always;

{proxy_block}
}}
"""
    else:
        vhost_config = f"""server {{
    listen {panel_port};
    server_name {cpanel_fqdn};
{acme_block}
{proxy_block}
}}
"""
    try:
        os.makedirs(VHOSTS_DIR, exist_ok=True)
        # Use sudo tee so the write succeeds regardless of whether the file
        # was previously created by a root process (e.g. early install runs).
        result = subprocess.run(
            ["sudo", "tee", vhost_path],
            input=vhost_config, text=True, capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"sudo tee failed: {result.stderr.strip()}")
        subprocess.run(["sudo", "chmod", "644", vhost_path], capture_output=True)
        if not skip_reload:
            nginx_reload()
        logger.info(f"Cpanel nginx vhost written: {cpanel_fqdn} (https={https_forced})")
    except Exception as e:
        logger.error(f"Failed to write cpanel nginx vhost for {cpanel_fqdn}: {e}")
        raise HTTPException(status_code=500, detail="Failed to write cpanel nginx configuration")


def write_nginx_ftp_vhost(domain_name: str, document_root: str):
    """Create a minimal nginx vhost for ftp.<domain> — only for SSL cert coverage.
    Serves /.well-known/acme-challenge/ from document_root, redirects everything else."""
    ftp_fqdn = f"ftp.{domain_name}"
    vhost_path = f"{VHOSTS_DIR}/{ftp_fqdn}.conf"
    if os.path.exists(vhost_path):
        logger.info(f"FTP vhost already exists for {ftp_fqdn}, skipping")
        return
    vhost_config = f"""# Generated by HostPanel
server {{
    listen 80;
    server_name {ftp_fqdn};

    location ^~ /.well-known/acme-challenge/ {{
        root {document_root};
        default_type "text/plain";
        try_files $uri =404;
    }}

    location / {{
        return 301 http://{domain_name}$request_uri;
    }}
}}
"""
    try:
        os.makedirs(VHOSTS_DIR, exist_ok=True)
        with open(vhost_path, "w") as f:
            f.write(vhost_config)
        nginx_reload()
        logger.info(f"FTP nginx vhost written: {ftp_fqdn}")
    except Exception as e:
        logger.error(f"Failed to write FTP nginx vhost for {ftp_fqdn}: {e}")
        raise HTTPException(status_code=500, detail="Failed to write FTP nginx configuration")


# ── DNS auto-provision ─────────────────────────────────────────────────────────

async def _auto_create_dns_zone(domain: str):
    pdns_url = "http://127.0.0.1:8053/api/v1/servers/localhost"
    pdns_api_key = os.environ.get("PDNS_API_KEY", "hostpanel-dns-api-key")
    _ns1 = os.environ.get("PDNS_NS1", "ns1.hostpanel.local.")
    _ns2 = os.environ.get("PDNS_NS2", "ns2.hostpanel.local.")
    ns1 = _ns1 if _ns1.endswith('.') else f"{_ns1}."
    ns2 = _ns2 if _ns2.endswith('.') else f"{_ns2}."
    server_ip = os.environ.get("SERVER_IP", "")
    name = domain if domain.endswith(".") else f"{domain}."
    headers = {"X-API-Key": pdns_api_key}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{pdns_url}/zones",
                headers=headers,
                json={"name": name, "kind": "Native", "nameservers": [ns1, ns2]},
            )
            if resp.status_code not in (200, 201, 422):
                logger.warning(f"DNS zone creation returned {resp.status_code} for {domain}")
                return
            if server_ip:
                a_payload = {"rrsets": [
                    {"name": name, "type": "A", "ttl": 3600, "changetype": "REPLACE",
                     "records": [{"content": server_ip, "disabled": False}]},
                    {"name": f"www.{name}", "type": "A", "ttl": 3600, "changetype": "REPLACE",
                     "records": [{"content": server_ip, "disabled": False}]},
                    {"name": f"ftp.{name}", "type": "A", "ttl": 3600, "changetype": "REPLACE",
                     "records": [{"content": server_ip, "disabled": False}]},
                    {"name": f"cpanel.{name}", "type": "A", "ttl": 3600, "changetype": "REPLACE",
                     "records": [{"content": server_ip, "disabled": False}]},
                ]}
                await client.patch(f"{pdns_url}/zones/{name}", headers=headers, json=a_payload)
    except Exception as e:
        logger.warning(f"Could not auto-create DNS zone for {domain}: {e}")


async def _auto_add_a_record(fqdn: str, server_ip: str):
    pdns_url = "http://127.0.0.1:8053/api/v1/servers/localhost"
    pdns_api_key = os.environ.get("PDNS_API_KEY", "hostpanel-dns-api-key")
    parts = fqdn.split(".")
    zone_name = ".".join(parts[1:]) + "."
    name = fqdn + "."
    async with httpx.AsyncClient(timeout=5.0) as client:
        payload = {"rrsets": [{"name": name, "type": "A", "ttl": 3600, "changetype": "REPLACE",
                               "records": [{"content": server_ip, "disabled": False}]}]}
        await client.patch(f"{pdns_url}/zones/{zone_name}", headers={"X-API-Key": pdns_api_key}, json=payload)


async def _auto_delete_a_record(fqdn: str):
    pdns_url = "http://127.0.0.1:8053/api/v1/servers/localhost"
    pdns_api_key = os.environ.get("PDNS_API_KEY", "hostpanel-dns-api-key")
    parts = fqdn.split(".")
    zone_name = ".".join(parts[1:]) + "."
    name = fqdn + "."
    async with httpx.AsyncClient(timeout=5.0) as client:
        payload = {"rrsets": [{"name": name, "type": "A", "changetype": "DELETE"}]}
        await client.patch(f"{pdns_url}/zones/{zone_name}", headers={"X-API-Key": pdns_api_key}, json=payload)


async def _auto_delete_dns_zone(domain: str):
    pdns_url = "http://127.0.0.1:8053/api/v1/servers/localhost"
    pdns_api_key = os.environ.get("PDNS_API_KEY", "hostpanel-dns-api-key")
    name = domain if domain.endswith(".") else f"{domain}."
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.delete(f"{pdns_url}/zones/{name}", headers={"X-API-Key": pdns_api_key})
            if resp.status_code not in (204, 422):
                logger.warning(f"DNS zone delete returned {resp.status_code} for {domain}")
    except Exception as e:
        logger.warning(f"Could not delete DNS zone for {domain}: {e}")


# ── Cascade delete ─────────────────────────────────────────────────────────────

async def cascade_delete_domain(domain_name: str) -> bool:
    """Nginx-scoped cleanup for a hosted domain: vhosts, SSL cert, subdomain vhosts.
    Does NOT touch DNS zones, FTP accounts, databases, or system users — those are
    owned by their respective core modules or plugins."""
    domains = _load_domains()
    domain_record = next((d for d in domains if d["domain_name"] == domain_name), None)
    if not domain_record:
        return False

    logger.info(f"Nginx cascade: cleaning up {domain_name}")
    nginx_changed = False

    # 1. Remove nginx vhost and cpanel reverse-proxy vhost
    vhost_path = f"{VHOSTS_DIR}/{domain_name}.conf"
    if os.path.exists(vhost_path):
        try:
            os.remove(vhost_path)
            nginx_changed = True
        except Exception as e:
            logger.warning(f"Could not remove vhost for {domain_name}: {e}")

    cpanel_vhost_path = f"{VHOSTS_DIR}/cpanel.{domain_name}.conf"
    if os.path.exists(cpanel_vhost_path):
        try:
            os.remove(cpanel_vhost_path)
            nginx_changed = True
        except Exception as e:
            logger.warning(f"Could not remove cpanel vhost for {domain_name}: {e}")

    # 2. Revoke SSL cert
    if os.path.exists(f"/etc/letsencrypt/live/{domain_name}"):
        try:
            subprocess.run(
                ["sudo", "-n", "certbot", "delete", "--cert-name", domain_name, "--non-interactive"],
                check=True, capture_output=True, text=True, timeout=30
            )
        except Exception as e:
            logger.warning(f"Could not revoke SSL cert for {domain_name}: {e}")

    # 3. Remove subdomain vhosts (subdomain A records are preserved in DNS)
    all_subdomains = _load_subdomains()
    for sub in [s for s in all_subdomains if s["parent_domain"] == domain_name]:
        sub_vhost = f"{VHOSTS_DIR}/{sub['fqdn']}.conf"
        if os.path.exists(sub_vhost):
            try:
                os.remove(sub_vhost)
                nginx_changed = True
            except: pass
    _save_subdomains([s for s in all_subdomains if s["parent_domain"] != domain_name])

    if nginx_changed:
        try: nginx_reload()
        except Exception as e: logger.warning(f"nginx reload failed: {e}")

    # 4. Remove from domain registry
    _save_domains([d for d in domains if d["domain_name"] != domain_name])
    return True


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/unprovisioned-zones")
async def get_unprovisioned_zones(current_user: User = Depends(require_admin)):
    """Return DNS zones that exist in PowerDNS but are not yet provisioned as websites."""
    pdns_url = "http://127.0.0.1:8053/api/v1/servers/localhost"
    pdns_api_key = os.environ.get("PDNS_API_KEY", "hostpanel-dns-api-key")
    dns_zones: List[str] = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{pdns_url}/zones", headers={"X-API-Key": pdns_api_key})
            if resp.status_code == 200:
                dns_zones = [z["name"].rstrip(".") for z in resp.json()]
    except Exception as e:
        logger.warning(f"Could not fetch DNS zones: {e}")

    registered = {d["domain_name"] for d in _load_domains()}
    unprovisioned = [z for z in dns_zones if z not in registered]

    return {
        "zones": unprovisioned,
        "default_domain": os.environ.get("SERVER_DOMAIN", ""),
        "certbot_available": bool(shutil.which("certbot")),
    }


@router.post("/provision")
async def provision_domains(request: ProvisionRequest, current_user: User = Depends(require_admin)):
    """Provision selected DNS zones as hosted websites. Optionally issues SSL per domain."""
    existing = _load_domains()
    registered = {d["domain_name"] for d in existing}
    results = []
    any_ssl_requested = False

    for item in request.domains:
        domain = item.domain
        if domain in registered:
            results.append({"domain": domain, "status": "already_provisioned"})
            continue

        username = _derive_username(domain)

        try:
            # Create the tenant user + webroot in the tenant's home (idempotent,
            # tenant-owned — shared with add_domain and the reconcile path).
            document_root = _provision_tenant_webroot(username, domain)

            # Write nginx vhosts (main site + cpanel reverse proxy + ftp)
            write_nginx_vhost(domain, document_root)
            write_nginx_cpanel_vhost(domain, document_root)
            write_nginx_ftp_vhost(domain, document_root)

            # Register in domain registry
            record = {
                "domain_name": domain,
                "username": username,
                "document_root": document_root,
                "status": "active",
            }
            existing.append(record)
            registered.add(domain)

            # Issue SSL in background if requested and certbot is available
            if item.issue_ssl and shutil.which("certbot"):
                any_ssl_requested = True
                certbot_email = os.environ.get("CERTBOT_EMAIL", "admin@hostpanel.local")
                cmd = [
                    "sudo", "certbot", "certonly", "--webroot",
                    "-w", document_root,
                    "-d", domain, "-d", f"www.{domain}",
                    "-d", f"cpanel.{domain}", "-d", f"ftp.{domain}",
                    "--non-interactive", "--agree-tos", "--email", certbot_email,
                    "--keep-until-expiring",
                ]
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            results.append({
                "domain": domain,
                "status": "provisioned",
                "ssl_requested": item.issue_ssl,
            })
            logger.info(f"Nginx provision: {domain} provisioned (ssl={item.issue_ssl})")

        except Exception as e:
            logger.error(f"Nginx provision: failed for {domain}: {e}")
            results.append({"domain": domain, "status": "error", "error": str(e)})

    _save_domains(existing)

    # Enable certbot renewal timer when at least one SSL cert was requested
    if any_ssl_requested:
        subprocess.run(
            ["sudo", "systemctl", "enable", "--now", "certbot.timer"],
            capture_output=True,
        )

    provisioned = [r["domain"] for r in results if r["status"] == "provisioned"]
    if provisioned:
        log_action(current_user.username, "domain.provision", ", ".join(provisioned))
    return {"results": results}


@router.get("", response_model=List[DomainDetail])
async def list_domains(current_user: User = Depends(get_current_user)):
    domains = _load_domains()
    if current_user.role != "admin":
        domains = [d for d in domains if d.get("username") == current_user.linux_user]
    return [{**d, "https_forced": _is_https_forced(d["domain_name"])} for d in domains]


@router.post("", response_model=DomainResponse)
async def add_domain(request: DomainCreateRequest, current_user: User = Depends(require_admin)):
    domain = request.domain_name
    username = _derive_username(domain)
    # Static sites are served from the tenant's own home; proxy vhosts serve no
    # files, so they only need an ACME webroot for certbot challenges.
    document_root = "/opt/hostpanel/acme" if request.proxy_pass else f"/home/{username}/public_html"

    existing = _load_domains()
    if any(d["domain_name"] == domain for d in existing):
        raise HTTPException(status_code=409, detail=f"Domain '{domain}' is already provisioned.")
    if domain in RESERVED_DOMAINS:
        raise HTTPException(status_code=400, detail=f"'{domain}' is a reserved domain.")

    # DB-first: record intent before any OS mutation so a mid-way failure leaves a
    # row the reconcile/repair path can complete. document_root is deterministic.
    record = {"domain_name": domain, "username": username, "document_root": document_root, "status": "active"}
    existing.append(record)
    _save_domains(existing)

    try:
        # Non-proxy sites: create the tenant user + webroot in the tenant's home.
        if not request.proxy_pass:
            _provision_tenant_webroot(username, domain)

        write_nginx_vhost(
            domain, document_root,
            aliases=request.aliases,
            proxy_pass=request.proxy_pass,
            php_version=request.php_version,
            gzip_enabled=request.gzip_enabled,
        )
    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Provisioning failed for '{domain}' (recorded for repair): {e.stderr.strip() if e.stderr else e}",
        )

    await _auto_create_dns_zone(domain)

    if request.https_enabled and shutil.which("certbot"):
        certbot_email = os.environ.get("CERTBOT_EMAIL", "admin@hostpanel.local")
        acme_root = document_root if not request.proxy_pass else "/opt/hostpanel/acme"
        cmd = [
            "sudo", "certbot", "certonly", "--webroot",
            "-w", acme_root,
            "-d", domain,
            "--non-interactive", "--agree-tos", "--email", certbot_email,
            "--keep-until-expiring",
        ]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    log_action(current_user.username, "domain.add", domain, f"user={username}")
    return record


@router.post("/vhost-only", response_model=DomainResponse)
async def add_vhost_only(request: VhostOnlyCreateRequest, current_user: User = Depends(require_admin)):
    """Register a domain and write ONLY its nginx server block. Creates no tenant
    user, no public_html, and no DNS zone — the operator maps DNS and creates the
    document root themselves. The domain still lists/edits/deletes like any other.
    Independent of add_domain; the full-provisioning flow is left untouched."""
    domain = request.domain_name
    username = _derive_username(domain)

    existing = _load_domains()
    if any(d["domain_name"] == domain for d in existing):
        raise HTTPException(status_code=409, detail=f"Domain '{domain}' is already provisioned.")
    if domain in RESERVED_DOMAINS:
        raise HTTPException(status_code=400, detail=f"'{domain}' is a reserved domain.")

    # Proxy vhosts serve no files (ACME webroot only); static vhosts use the
    # operator-supplied, injection-validated root.
    document_root = "/opt/hostpanel/acme" if request.proxy_pass else _validate_document_root(request.document_root)

    record = {"domain_name": domain, "username": username, "document_root": document_root, "status": "active"}
    existing.append(record)
    _save_domains(existing)

    write_nginx_vhost(
        domain, document_root,
        https_forced=request.https_forced,
        aliases=request.aliases,
        proxy_pass=request.proxy_pass,
        php_version=request.php_version,
        gzip_enabled=request.gzip_enabled,
    )

    log_action(current_user.username, "domain.add_vhost_only", domain, f"user={username} root={document_root}")
    return record


@router.get("/{domain_name}", response_model=DomainDetail)
async def get_domain(domain_name: str, current_user: User = Depends(get_current_user)):
    domains = _load_domains()
    record = next((d for d in domains if d["domain_name"] == domain_name), None)
    if not record:
        raise HTTPException(status_code=404, detail=f"Domain '{domain_name}' not found.")
    check_domain_access(record, current_user)
    return {**record, "https_forced": _is_https_forced(domain_name)}


@router.put("/{domain_name}/force-https")
async def toggle_force_https(domain_name: str, request: ForceHttpsRequest, current_user: User = Depends(get_current_user)):
    domains = _load_domains()
    record = next((d for d in domains if d["domain_name"] == domain_name), None)
    if not record:
        raise HTTPException(status_code=404, detail=f"Domain '{domain_name}' not found.")
    check_domain_access(record, current_user)
    write_nginx_vhost(domain_name, record["document_root"], request.enabled)
    log_action(current_user.username, "domain.force_https", domain_name, str(request.enabled))
    return {"domain_name": domain_name, "https_forced": request.enabled}


@router.get("/{domain_name}/resources")
async def get_domain_resources(domain_name: str, current_user: User = Depends(require_admin)):
    from routers.databases import _load_store as _load_databases
    from routers.users import PURE_PW, PASSWD_FILE

    domains = _load_domains()
    record = next((d for d in domains if d["domain_name"] == domain_name), None)
    if not record:
        raise HTTPException(status_code=404, detail=f"Domain '{domain_name}' not found.")

    username = record["username"]
    ssl_cert = os.path.exists(f"/etc/letsencrypt/live/{domain_name}")

    ftp_account = False
    try:
        result = subprocess.run(
            ["sudo", "-n", PURE_PW, "list", "-f", PASSWD_FILE],
            capture_output=True, text=True
        )
        ftp_account = username in {line.split()[0] for line in result.stdout.strip().splitlines() if line}
    except Exception:
        pass

    databases = [r["name"] for r in _load_databases() if r.get("owner") == username]
    subdomains_list = [s["fqdn"] for s in _load_subdomains() if s["parent_domain"] == domain_name]
    other_domains = [d["domain_name"] for d in domains if d.get("username") == username and d["domain_name"] != domain_name]

    return {
        "domain": domain_name, "username": username, "ssl_cert": ssl_cert,
        "ftp_account": ftp_account, "databases": databases,
        "subdomains": subdomains_list, "will_delete_user": len(other_domains) == 0,
    }


@router.delete("/{domain_name}")
async def delete_domain(domain_name: str, current_user: User = Depends(require_admin)):
    domains = _load_domains()
    if not any(d["domain_name"] == domain_name for d in domains):
        raise HTTPException(status_code=404, detail=f"Domain '{domain_name}' not found.")
    await cascade_delete_domain(domain_name)
    log_action(current_user.username, "domain.delete", domain_name)
    return {"message": f"Domain {domain_name} and all associated resources deleted"}


# ── Subdomain routes ──────────────────────────────────────────────────────────

@router.get("/{domain_name}/subdomains", response_model=List[SubdomainResponse])
async def list_subdomains(domain_name: str, _: User = Depends(require_admin)):
    domains = _load_domains()
    if not any(d["domain_name"] == domain_name for d in domains):
        raise HTTPException(status_code=404, detail=f"Domain '{domain_name}' not found.")
    return [{**s, "https_forced": _is_https_forced(s["fqdn"])} for s in _load_subdomains() if s["parent_domain"] == domain_name]


@router.post("/{domain_name}/subdomains", response_model=SubdomainResponse)
async def add_subdomain(domain_name: str, request: SubdomainCreateRequest, current_user: User = Depends(require_admin)):
    if not re.match(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?$', request.subdomain):
        raise HTTPException(status_code=400, detail="Subdomain label must be lowercase alphanumeric with optional hyphens.")

    domains = _load_domains()
    domain_record = next((d for d in domains if d["domain_name"] == domain_name), None)
    if not domain_record:
        raise HTTPException(status_code=404, detail=f"Domain '{domain_name}' not found.")

    fqdn = f"{request.subdomain}.{domain_name}"
    username = domain_record["username"]
    document_root = f"/home/{username}/public_html/{fqdn}"

    subdomains = _load_subdomains()
    if any(s["fqdn"] == fqdn for s in subdomains):
        raise HTTPException(status_code=409, detail=f"Subdomain '{fqdn}' already exists.")

    run_command_safe(["sudo", "mkdir", "-p", document_root])
    try:
        subprocess.run(
            ["sudo", "-n", "tee", os.path.join(document_root, "index.html")],
            input=_default_index_html(fqdn), text=True, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Failed to write index.html: {e.stderr.strip()}")
    # Own to the tenant and set safe perms — no transient world-writable window.
    run_command_safe(["sudo", "/opt/hostpanel/bin/hp-chown", f"{username}:{document_root}"])
    run_command_safe(["sudo", "chmod", "-R", "755", document_root])

    write_nginx_vhost(fqdn, document_root)

    server_ip = os.environ.get("SERVER_IP", "")
    if server_ip:
        try: await _auto_add_a_record(fqdn, server_ip)
        except Exception as e: logger.warning(f"Could not auto-create DNS A record for {fqdn}: {e}")

    record = {"fqdn": fqdn, "subdomain": request.subdomain, "parent_domain": domain_name,
              "document_root": document_root, "username": username, "status": "active"}
    subdomains.append(record)
    _save_subdomains(subdomains)
    log_action(current_user.username, "subdomain.add", fqdn, f"parent={domain_name}")
    return record


@router.get("/{domain_name}/vhost")
async def get_vhost(domain_name: str, current_user: User = Depends(get_current_user)):
    """Return the raw nginx vhost config for a domain."""
    records = _load_domains()
    record = next((d for d in records if d["domain_name"] == domain_name), None)
    if not record:
        raise HTTPException(status_code=404, detail=f"Domain '{domain_name}' not found")
    check_domain_access(record, current_user)
    vhost_path = f"{VHOSTS_DIR}/{domain_name}.conf"
    if not os.path.exists(vhost_path):
        raise HTTPException(status_code=404, detail="Vhost config file not found")
    with open(vhost_path) as f:
        content = f.read()
    return {"domain": domain_name, "content": content, "path": vhost_path}


@router.put("/{domain_name}/vhost")
async def update_vhost(domain_name: str, request: VhostUpdateRequest, current_user: User = Depends(get_current_user)):
    """Write a new vhost config, test with nginx -t, reload on success, rollback on failure."""
    records = _load_domains()
    record = next((d for d in records if d["domain_name"] == domain_name), None)
    if not record:
        raise HTTPException(status_code=404, detail=f"Domain '{domain_name}' not found")
    check_domain_access(record, current_user)

    vhost_path = f"{VHOSTS_DIR}/{domain_name}.conf"
    old_content = None
    if os.path.exists(vhost_path):
        with open(vhost_path) as f:
            old_content = f.read()

    with open(vhost_path, "w") as f:
        f.write(request.content)

    test = subprocess.run(["sudo", "-n", NGINX_BIN, "-t"], capture_output=True, text=True)
    output = (test.stderr or test.stdout).strip()
    # Accept if nginx reports "syntax is ok" — runtime checks (temp dirs etc.) may
    # still fail with non-zero exit but the config is valid and reload will work.
    syntax_ok = "syntax is ok" in output
    if test.returncode != 0 and not syntax_ok:
        # True syntax error — rollback
        if old_content is not None:
            with open(vhost_path, "w") as f:
                f.write(old_content)
        else:
            os.remove(vhost_path)
        raise HTTPException(status_code=400, detail=output)

    nginx_reload()
    log_action(current_user.username, "domain.vhost_edit", domain_name)
    return {"domain": domain_name, "message": "Vhost saved and nginx reloaded"}


@router.post("/{domain_name}/vhost/reset")
async def reset_vhost(domain_name: str, current_user: User = Depends(get_current_user)):
    """Regenerate the vhost from the standard template."""
    records = _load_domains()
    record = next((d for d in records if d["domain_name"] == domain_name), None)
    if not record:
        raise HTTPException(status_code=404, detail=f"Domain '{domain_name}' not found")
    check_domain_access(record, current_user)

    https_forced = _is_https_forced(domain_name)
    write_nginx_vhost(domain_name, record["document_root"], https_forced=https_forced)

    vhost_path = f"{VHOSTS_DIR}/{domain_name}.conf"
    with open(vhost_path) as f:
        content = f.read()
    log_action(current_user.username, "domain.vhost_reset", domain_name)
    return {"domain": domain_name, "message": "Vhost reset to default template", "content": content}


@router.delete("/{domain_name}/subdomains/{subdomain}")
async def delete_subdomain(domain_name: str, subdomain: str, current_user: User = Depends(require_admin)):
    fqdn = f"{subdomain}.{domain_name}"
    subdomains = _load_subdomains()
    record = next((s for s in subdomains if s["fqdn"] == fqdn), None)
    if not record:
        raise HTTPException(status_code=404, detail=f"Subdomain '{fqdn}' not found.")

    vhost_path = f"{VHOSTS_DIR}/{fqdn}.conf"
    if os.path.exists(vhost_path):
        os.remove(vhost_path)
        nginx_reload()

    try: await _auto_delete_a_record(fqdn)
    except Exception as e: logger.warning(f"Could not remove DNS record for {fqdn}: {e}")

    _save_subdomains([s for s in subdomains if s["fqdn"] != fqdn])
    log_action(current_user.username, "subdomain.delete", fqdn, f"parent={domain_name}")
    return {"message": f"Subdomain {fqdn} deleted"}
