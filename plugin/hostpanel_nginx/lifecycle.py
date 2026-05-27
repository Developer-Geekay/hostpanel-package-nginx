import logging
import os
import subprocess

from fastapi import HTTPException

logger = logging.getLogger(__name__)

LETSENCRYPT_DIR = "/etc/letsencrypt/live"
SERVICE_NAME = "hostpanel-nginx"
SERVICE_DST = f"/etc/systemd/system/{SERVICE_NAME}.service"
NGINX_DIR = "/opt/hostpanel/plugins/nginx"


def on_install():
    """Install hostpanel-nginx service, enable, and start it."""
    logger.info("Nginx on_install: setting up service")

    # Create required runtime directories
    os.makedirs(f"{NGINX_DIR}/vhosts", exist_ok=True)
    os.makedirs(f"{NGINX_DIR}/logs",   exist_ok=True)

    # Copy nginx.conf and mime.types from conf/ (placed by package manager)
    conf_src_dir = os.path.join(NGINX_DIR, "conf")
    for fname in ("nginx.conf", "mime.types"):
        src = os.path.join(conf_src_dir, fname)
        dst = os.path.join(NGINX_DIR, fname)
        if os.path.exists(src) and not os.path.exists(dst):
            with open(src) as f:
                content = f.read()
            subprocess.run(["sudo", "tee", dst], input=content, text=True, capture_output=True)
            subprocess.run(["sudo", "chmod", "644", dst], capture_output=True)
            logger.info(f"Installed {fname} → {dst}")

    # Install service file from service/ directory (package manager puts it there)
    if not os.path.exists(SERVICE_DST):
        svc_src = os.path.join(NGINX_DIR, "service", f"{SERVICE_NAME}.service")
        if os.path.exists(svc_src):
            try:
                with open(svc_src) as f:
                    content = f.read()
                r = subprocess.run(
                    ["sudo", "tee", SERVICE_DST],
                    input=content, text=True, capture_output=True,
                )
                if r.returncode == 0:
                    subprocess.run(["sudo", "chmod", "644", SERVICE_DST], capture_output=True)
                    logger.info(f"Installed service file → {SERVICE_DST}")
            except Exception as e:
                logger.warning(f"Could not install service file: {e}")
        else:
            logger.warning(f"Service file not found at {svc_src}")

    subprocess.run(["sudo", "systemctl", "daemon-reload"], capture_output=True)
    subprocess.run(["sudo", "systemctl", "enable", SERVICE_NAME], capture_output=True)
    subprocess.run(["sudo", "systemctl", "start",  SERVICE_NAME], capture_output=True)
    logger.info("Nginx on_install: service enabled and started")


async def pre_uninstall(force: bool = False):
    """Called before package uninstall. Blocks if domains are still provisioned.
    On force: removes only nginx-owned resources (vhosts, SSL certs).
    DNS zones, FTP accounts, databases, and system users are NOT touched."""
    from domain_registry import _load_domains, _save_domains, _load_subdomains, _save_subdomains
    from hostpanel_nginx.domains import VHOSTS_DIR, nginx_reload

    domains = _load_domains()
    if domains and not force:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot uninstall: {len(domains)} domain(s) still provisioned. Use force=True to remove them."
        )

    # Service is only stopped when uninstall will actually proceed
    subprocess.run(["sudo", "systemctl", "stop", SERVICE_NAME], capture_output=True)
    subprocess.run(["sudo", "systemctl", "disable", SERVICE_NAME], capture_output=True)
    subprocess.run(["sudo", "rm", "-f", SERVICE_DST], capture_output=True)
    subprocess.run(["sudo", "systemctl", "daemon-reload"], capture_output=True)
    logger.info(f"Nginx pre_uninstall: service stopped and removed")
    if domains and force:
        logger.info(f"Force-uninstalling nginx plugin: cleaning {len(domains)} domain(s) (vhosts + SSL only)")
        nginx_changed = False

        for domain_rec in list(domains):
            domain_name = domain_rec["domain_name"]

            # Remove main vhost
            vhost_path = f"{VHOSTS_DIR}/{domain_name}.conf"
            if os.path.exists(vhost_path):
                try:
                    os.remove(vhost_path)
                    nginx_changed = True
                except Exception as e:
                    logger.warning(f"Could not remove vhost for {domain_name}: {e}")

            # Revoke SSL cert
            if os.path.exists(f"{LETSENCRYPT_DIR}/{domain_name}"):
                try:
                    subprocess.run(
                        ["sudo", "certbot", "delete", "--cert-name", domain_name, "--non-interactive"],
                        check=True, capture_output=True, text=True, timeout=30
                    )
                except Exception as e:
                    logger.warning(f"Could not revoke SSL for {domain_name}: {e}")

        # Remove subdomain vhosts
        all_subdomains = _load_subdomains()
        for sub in all_subdomains:
            sub_vhost = f"{VHOSTS_DIR}/{sub['fqdn']}.conf"
            if os.path.exists(sub_vhost):
                try:
                    os.remove(sub_vhost)
                    nginx_changed = True
                except: pass

        if nginx_changed:
            try: nginx_reload()
            except Exception as e: logger.warning(f"nginx reload failed: {e}")

        # Clear domain and subdomain registry (nginx owns these records)
        _save_domains([])
        _save_subdomains([])

    if force and os.path.isdir(NGINX_DIR):
        subprocess.run(["sudo", "rm", "-rf", NGINX_DIR], capture_output=True)
        logger.info(f"Nginx pre_uninstall: removed {NGINX_DIR}")

    # Remove plugin sudoers last — all cleanup above still needs those permissions
    subprocess.run(["sudo", "rm", "-f", "/etc/sudoers.d/hostpanel-nginx"], capture_output=True)
    logger.info("Nginx plugin uninstalled: vhosts, SSL certs, binaries, and sudoers removed. DNS zones preserved.")


async def on_startup():
    """Called at server startup. Ensures nginx service is running and provisions
    vhosts for any domains in the registry that don't already have a config."""
    from domain_registry import _load_domains, _load_subdomains
    from hostpanel_nginx.domains import write_nginx_vhost, VHOSTS_DIR

    result = subprocess.run(
        ["sudo", "systemctl", "is-active", SERVICE_NAME],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        logger.info(f"Nginx on_startup: service not active ({result.stdout.strip()}), starting...")
        subprocess.run(["sudo", "systemctl", "start", SERVICE_NAME], capture_output=True)
    else:
        logger.info(f"Nginx on_startup: service is active")

    domains = _load_domains()
    if not domains:
        return

    provisioned = 0
    for domain_rec in domains:
        domain_name = domain_rec["domain_name"]
        doc_root = domain_rec.get("document_root", f"/home/{domain_rec.get('username', 'web')}/public_html")
        write_nginx_vhost(domain_name, doc_root, https_forced=False, skip_if_exists=True)
        provisioned += 1

    subdomains = _load_subdomains()
    for sub in subdomains:
        write_nginx_vhost(sub["fqdn"], sub["document_root"], https_forced=False, skip_if_exists=True)
        provisioned += 1

    if provisioned:
        logger.info(f"Nginx on_startup: checked {provisioned} domain/subdomain vhost(s), created any that were missing")


async def on_user_delete(username: str, **kwargs):
    """Called by core when a hosting user is deleted. Cleans up nginx vhosts and SSL certs.
    DNS zones are NOT deleted here — DNS is managed by core independently."""
    from domain_registry import _load_domains, _save_domains, _load_subdomains, _save_subdomains
    from hostpanel_nginx.domains import VHOSTS_DIR, nginx_reload

    all_domains = _load_domains()
    user_domains = [d for d in all_domains if d.get("username") == username]
    user_domain_names = {d["domain_name"] for d in user_domains}

    nginx_changed = False
    for domain_rec in user_domains:
        domain_name = domain_rec["domain_name"]
        vhost_path = f"{VHOSTS_DIR}/{domain_name}.conf"
        if os.path.exists(vhost_path):
            try:
                os.remove(vhost_path)
                nginx_changed = True
            except Exception as e:
                logger.warning(f"Could not remove vhost for {domain_name}: {e}")
        if os.path.exists(f"{LETSENCRYPT_DIR}/{domain_name}"):
            try:
                subprocess.run(
                    ["sudo", "certbot", "delete", "--cert-name", domain_name, "--non-interactive"],
                    check=True, capture_output=True, text=True, timeout=30
                )
            except Exception as e:
                logger.warning(f"Could not revoke SSL for {domain_name}: {e}")

    all_subdomains = _load_subdomains()
    for sub in all_subdomains:
        if sub.get("parent_domain") in user_domain_names:
            sub_vhost = f"{VHOSTS_DIR}/{sub['fqdn']}.conf"
            if os.path.exists(sub_vhost):
                try:
                    os.remove(sub_vhost)
                    nginx_changed = True
                except: pass

    if nginx_changed:
        try: nginx_reload()
        except Exception as e: logger.warning(f"nginx reload failed: {e}")

    _save_domains([d for d in all_domains if d.get("username") != username])
    _save_subdomains([s for s in all_subdomains if s.get("parent_domain") not in user_domain_names])
    logger.info(f"Nginx plugin cleaned up vhosts/SSL for deleted user: {username} (DNS zones preserved)")


async def on_domain_delete(domain: str, **kwargs):
    """Called by core (dns.py) when a DNS zone is deleted that had an associated hosted domain."""
    from hostpanel_nginx.domains import cascade_delete_domain
    await cascade_delete_domain(domain)


async def on_ssl_force_https(domain: str, enabled: bool, doc_root: str = None, **kwargs):
    """Called by core SSL when force-HTTPS is toggled. Rewrites the nginx vhost."""
    from hostpanel_nginx.domains import write_nginx_vhost
    from domain_registry import _load_domains
    if doc_root is None:
        rec = next((d for d in _load_domains() if d["domain_name"] == domain), None)
        if not rec:
            return
        doc_root = rec["document_root"]
    try:
        write_nginx_vhost(domain, doc_root, https_forced=enabled)
        logger.info(f"Nginx vhost updated: force-HTTPS={'on' if enabled else 'off'} for {domain}")
    except Exception as e:
        logger.warning(f"Could not update nginx vhost for {domain}: {e}")


async def on_ssl_cert_deleted(domain: str, doc_root: str = None, **kwargs):
    """Called by core SSL when a cert is deleted. Downgrades the nginx vhost to plain HTTP."""
    from hostpanel_nginx.domains import write_nginx_vhost
    from domain_registry import _load_domains
    if doc_root is None:
        rec = next((d for d in _load_domains() if d["domain_name"] == domain), None)
        if not rec:
            return
        doc_root = rec["document_root"]
    try:
        write_nginx_vhost(domain, doc_root, https_forced=False)
        logger.info(f"Nginx vhost downgraded to HTTP after cert deletion for {domain}")
    except Exception as e:
        logger.warning(f"Could not downgrade nginx vhost for {domain}: {e}")
