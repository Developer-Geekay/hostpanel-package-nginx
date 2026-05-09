import json
import logging
import os
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List

from auth import User
from deps import get_current_user
from domain_registry import _load_domains, check_domain_access
from hostpanel_nginx.domains import _is_https_forced, nginx_reload, VHOSTS_DIR

router = APIRouter(prefix="/cpanelapi/redirects", tags=["Redirects"])
logger = logging.getLogger(__name__)

REDIRECTS_FILE = "/opt/hostpanel/redirects.json"
_SERVER_DOMAIN = os.environ.get("SERVER_DOMAIN", "")
_RESERVED_PATHS = ("/cpanel", "/api")


class RedirectRecord(BaseModel):
    id: str
    source_domain: str
    source_path: str
    destination: str
    type: int
    www_handling: str

class CreateRedirectRequest(BaseModel):
    source_domain: str
    source_path: str
    destination: str
    type: int = 301
    www_handling: str = "both"


def _load_redirects() -> List[dict]:
    if not os.path.exists(REDIRECTS_FILE):
        return []
    with open(REDIRECTS_FILE, "r") as f:
        return json.load(f)


def _save_redirects(redirects: List[dict]):
    os.makedirs(os.path.dirname(REDIRECTS_FILE), exist_ok=True)
    with open(REDIRECTS_FILE, "w") as f:
        json.dump(redirects, f, indent=2)


def _rebuild_vhost(domain_name: str):
    domains = _load_domains()
    record = next((d for d in domains if d["domain_name"] == domain_name), None)
    if not record:
        return
    doc_root     = record["document_root"]
    https_forced = _is_https_forced(domain_name)
    redirects    = [r for r in _load_redirects() if r["source_domain"] == domain_name]

    redirect_blocks = ""
    for r in redirects:
        redirect_blocks += f"\n    location = {r['source_path']} {{\n        return {r['type']} {r['destination']};\n    }}\n"

    if https_forced:
        config = (
            f"server {{\n    listen 80;\n    server_name {domain_name} www.{domain_name};\n"
            f"    return 301 https://$host$request_uri;\n}}\n\n"
            f"server {{\n    listen 443 ssl;\n    server_name {domain_name} www.{domain_name};\n"
            f"    root {doc_root};\n    index index.php index.html index.htm;\n\n"
            f"    access_log /opt/hostpanel/nginx/logs/{domain_name}.access.log;\n"
            f"    error_log  /opt/hostpanel/nginx/logs/{domain_name}.error.log;\n"
            f"{redirect_blocks}\n    location / {{\n        try_files $uri $uri/ /index.html;\n    }}\n}}\n"
        )
    else:
        config = (
            f"server {{\n    listen 80;\n    server_name {domain_name} www.{domain_name};\n"
            f"    root {doc_root};\n    index index.php index.html index.htm;\n\n"
            f"    access_log /opt/hostpanel/nginx/logs/{domain_name}.access.log;\n"
            f"    error_log  /opt/hostpanel/nginx/logs/{domain_name}.error.log;\n"
            f"{redirect_blocks}\n    location / {{\n        try_files $uri $uri/ /index.html;\n    }}\n}}\n"
        )

    os.makedirs(VHOSTS_DIR, exist_ok=True)
    with open(f"{VHOSTS_DIR}/{domain_name}.conf", "w") as f:
        f.write(config)
    nginx_reload()


@router.get("", response_model=List[RedirectRecord])
async def list_redirects(current_user: User = Depends(get_current_user)):
    redirects = _load_redirects()
    if current_user.role != "admin":
        allowed = {d["domain_name"] for d in _load_domains() if d.get("username") == current_user.linux_user}
        redirects = [r for r in redirects if r["source_domain"] in allowed]
    return redirects


@router.post("", response_model=RedirectRecord, status_code=201)
async def create_redirect(request: CreateRedirectRequest, current_user: User = Depends(get_current_user)):
    if not request.source_path.startswith("/"):
        raise HTTPException(status_code=422, detail="source_path must start with /")
    if request.source_domain in (_SERVER_DOMAIN, f"www.{_SERVER_DOMAIN}"):
        if any(request.source_path == p or request.source_path.startswith(p + "/") for p in _RESERVED_PATHS):
            raise HTTPException(status_code=400, detail=f"Path '{request.source_path}' is reserved.")
    domains = _load_domains()
    domain_record = next((d for d in domains if d["domain_name"] == request.source_domain), None)
    if not domain_record:
        raise HTTPException(status_code=404, detail=f"Domain '{request.source_domain}' not provisioned.")
    check_domain_access(domain_record, current_user)
    if request.type not in (301, 302):
        raise HTTPException(status_code=422, detail="type must be 301 or 302")
    record: dict = {"id": str(uuid.uuid4()), "source_domain": request.source_domain,
                    "source_path": request.source_path, "destination": request.destination,
                    "type": request.type, "www_handling": request.www_handling}
    redirects = _load_redirects()
    redirects.append(record)
    _save_redirects(redirects)
    _rebuild_vhost(request.source_domain)
    return record


@router.delete("/{redirect_id}")
async def delete_redirect(redirect_id: str, current_user: User = Depends(get_current_user)):
    redirects = _load_redirects()
    target = next((r for r in redirects if r["id"] == redirect_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Redirect not found.")
    domain = target["source_domain"]
    domains = _load_domains()
    domain_record = next((d for d in domains if d["domain_name"] == domain), None)
    if domain_record:
        check_domain_access(domain_record, current_user)
    _save_redirects([r for r in redirects if r["id"] != redirect_id])
    _rebuild_vhost(domain)
    return {"message": "Redirect deleted"}
