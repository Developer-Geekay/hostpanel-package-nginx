import os
import logging
import re
import secrets
import string
import subprocess
import httpx
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from typing import List

from auth import User
from deps import get_current_user, require_admin
from domain_registry import (
    _load_domains, _save_domains,
    _load_subdomains, _save_subdomains,
    check_domain_access,
)

router = APIRouter(prefix="/cpanelapi/domains", tags=["Domains"])
logger = logging.getLogger(__name__)

NGINX_BIN  = "/opt/hostpanel/nginx/sbin/nginx"
VHOSTS_DIR = "/opt/hostpanel/nginx/vhosts"

RESERVED_DOMAINS = {"localhost", "127.0.0.1"}


# ── Models ─────────────────────────────────────────────────────────────────────

class DomainCreateRequest(BaseModel):
    domain_name: str

class SubdomainCreateRequest(BaseModel):
    subdomain: str

class SubdomainResponse(BaseModel):
    fqdn: str
    subdomain: str
    parent_domain: str
    document_root: str
    username: str
    status: str

class DomainResponse(BaseModel):
    domain_name: str
    username: str
    document_root: str
    status: str

class DomainDetail(DomainResponse):
    https_forced: bool

class ForceHttpsRequest(BaseModel):
    enabled: bool


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


def _derive_username(domain: str) -> str:
    label = domain.split(".")[0]
    safe = re.sub(r"[^a-z0-9_]", "", label.lower())[:32] or "web"
    return safe


def _random_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def run_command_safe(command: List[str]):
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
        return "return 301 https://" in f.read()


def write_nginx_vhost(domain_name: str, document_root: str, https_forced: bool = False, skip_if_exists: bool = False):
    if skip_if_exists and os.path.exists(f"{VHOSTS_DIR}/{domain_name}.conf"):
        logger.info(f"Nginx vhost already exists for {domain_name}, skipping")
        return
    if https_forced:
        vhost_config = f"""server {{
    listen 80;
    server_name {domain_name} www.{domain_name};

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
    server_name {domain_name} www.{domain_name};
    root {document_root};
    index index.php index.html index.htm;

    ssl_certificate     /etc/letsencrypt/live/{domain_name}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain_name}/privkey.pem;

    access_log /opt/hostpanel/nginx/logs/{domain_name}.access.log;
    error_log  /opt/hostpanel/nginx/logs/{domain_name}.error.log;

    location / {{
        try_files $uri $uri/ /index.html;
    }}
}}
"""
    else:
        vhost_config = f"""server {{
    listen 80;
    server_name {domain_name} www.{domain_name};
    root {document_root};
    index index.php index.html index.htm;

    access_log /opt/hostpanel/nginx/logs/{domain_name}.access.log;
    error_log  /opt/hostpanel/nginx/logs/{domain_name}.error.log;

    location ^~ /.well-known/acme-challenge/ {{
        default_type "text/plain";
        try_files $uri =404;
    }}

    location / {{
        try_files $uri $uri/ /index.html;
    }}
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


# ── DNS auto-provision ─────────────────────────────────────────────────────────

async def _auto_create_dns_zone(domain: str):
    pdns_url = "http://127.0.0.1:8053/api/v1/servers/localhost"
    pdns_api_key = os.environ.get("PDNS_API_KEY", "hostpanel-dns-api-key")
    ns1 = os.environ.get("PDNS_NS1", "ns1.hostpanel.local.")
    ns2 = os.environ.get("PDNS_NS2", "ns2.hostpanel.local.")
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

    # 1. Remove nginx vhost
    vhost_path = f"{VHOSTS_DIR}/{domain_name}.conf"
    if os.path.exists(vhost_path):
        try:
            os.remove(vhost_path)
            nginx_changed = True
        except Exception as e:
            logger.warning(f"Could not remove vhost for {domain_name}: {e}")

    # 2. Revoke SSL cert
    if os.path.exists(f"/etc/letsencrypt/live/{domain_name}"):
        try:
            subprocess.run(
                ["sudo", "certbot", "delete", "--cert-name", domain_name, "--non-interactive"],
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

@router.get("", response_model=List[DomainDetail])
async def list_domains(current_user: User = Depends(get_current_user)):
    domains = _load_domains()
    if current_user.role != "admin":
        domains = [d for d in domains if d.get("username") == current_user.linux_user]
    return [{**d, "https_forced": _is_https_forced(d["domain_name"])} for d in domains]


@router.post("", response_model=DomainResponse)
async def add_domain(request: DomainCreateRequest, current_user: User = Depends(require_admin)):
    from routers.users import get_sys_users, _create_linux_user

    domain = request.domain_name
    username = _derive_username(domain)
    password = _random_password()
    document_root = f"/home/{username}/public_html"

    existing = _load_domains()
    if any(d["domain_name"] == domain for d in existing):
        raise HTTPException(status_code=409, detail=f"Domain '{domain}' is already provisioned.")
    if domain in RESERVED_DOMAINS:
        raise HTTPException(status_code=400, detail=f"'{domain}' is a reserved domain.")

    user_list = get_sys_users()
    if not any(u["username"] == username for u in user_list):
        _create_linux_user(username, password)

    run_command_safe(["sudo", "mkdir", "-p", document_root])
    run_command_safe(["sudo", "chmod", "777", document_root])
    try:
        subprocess.run(
            ["sudo", "tee", os.path.join(document_root, "index.html")],
            input=_default_index_html(domain), text=True, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Failed to write index.html: {e.stderr.strip()}")
    run_command_safe(["sudo", "chown", "-R", f"{username}:{username}", f"/home/{username}/public_html"])
    run_command_safe(["sudo", "chmod", "-R", "755", f"/home/{username}"])

    write_nginx_vhost(domain, document_root)

    record = {"domain_name": domain, "username": username, "document_root": document_root, "status": "active"}
    existing.append(record)
    _save_domains(existing)

    await _auto_create_dns_zone(domain)
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
            ["sudo", PURE_PW, "list", "-f", PASSWD_FILE],
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
    return {"message": f"Domain {domain_name} and all associated resources deleted"}


# ── Subdomain routes ──────────────────────────────────────────────────────────

@router.get("/{domain_name}/subdomains", response_model=List[SubdomainResponse])
async def list_subdomains(domain_name: str, _: User = Depends(require_admin)):
    domains = _load_domains()
    if not any(d["domain_name"] == domain_name for d in domains):
        raise HTTPException(status_code=404, detail=f"Domain '{domain_name}' not found.")
    return [s for s in _load_subdomains() if s["parent_domain"] == domain_name]


@router.post("/{domain_name}/subdomains", response_model=SubdomainResponse)
async def add_subdomain(domain_name: str, request: SubdomainCreateRequest, _: User = Depends(require_admin)):
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
    run_command_safe(["sudo", "chmod", "777", document_root])
    try:
        subprocess.run(
            ["sudo", "tee", os.path.join(document_root, "index.html")],
            input=_default_index_html(fqdn), text=True, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Failed to write index.html: {e.stderr.strip()}")
    run_command_safe(["sudo", "chown", "-R", f"{username}:{username}", document_root])
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
    return record


@router.delete("/{domain_name}/subdomains/{subdomain}")
async def delete_subdomain(domain_name: str, subdomain: str, _: User = Depends(require_admin)):
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
    return {"message": f"Subdomain {fqdn} deleted"}
