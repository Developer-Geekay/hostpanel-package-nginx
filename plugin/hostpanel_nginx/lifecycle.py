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
    """Install hostpanel-nginx service, enable, and start it.
    If SERVER_DOMAIN is set in the environment, auto-provisions a website
    entry for the default domain and a cpanel reverse-proxy vhost."""
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

    # ── Auto-provision default domain ─────────────────────────────────────────
    _provision_default_domain()


def _provision_default_domain():
    """Provision a website entry and cpanel reverse-proxy vhost for the server's
    default domain (SERVER_DOMAIN env var, set during HostPanel installation).

    Safe to call on reinstall — checks domain registry before acting.
    Only the nginx vhosts and public_html are created here; the DNS zone and
    A records are assumed to already exist from the initial setup script.
    """
    server_domain = os.environ.get("SERVER_DOMAIN", "").strip()
    if not server_domain:
        logger.info("Nginx on_install: SERVER_DOMAIN not configured, skipping default domain provisioning")
        return

    from domain_registry import _load_domains, _save_domains
    from hostpanel_nginx.domains import (
        write_nginx_vhost, write_nginx_cpanel_vhost,
        _derive_username, _random_password, _default_index_html,
    )

    existing = _load_domains()
    already_registered = any(d["domain_name"] == server_domain for d in existing)

    if already_registered:
        # On reinstall: domain is in registry, just ensure cpanel vhost is present
        logger.info(f"Nginx on_install: {server_domain} already registered — ensuring cpanel vhost exists")
        try:
            write_nginx_cpanel_vhost(server_domain)
        except Exception as e:
            logger.warning(f"Nginx on_install: could not write cpanel vhost for {server_domain}: {e}")
        return

    logger.info(f"Nginx on_install: provisioning default domain {server_domain}")

    username = _derive_username(server_domain)
    password = _random_password()
    document_root = f"/home/{username}/public_html"

    # Create Linux user if not present
    try:
        from routers.users import get_sys_users, _create_linux_user
        if not any(u["username"] == username for u in get_sys_users()):
            _create_linux_user(username, password)
            logger.info(f"Nginx on_install: created Linux user '{username}'")
        else:
            logger.info(f"Nginx on_install: Linux user '{username}' already exists")
    except Exception as e:
        logger.warning(f"Nginx on_install: could not create Linux user '{username}': {e}")

    # Create public_html with a default index page
    try:
        subprocess.run(["sudo", "-n", "mkdir", "-p", document_root], capture_output=True)
        subprocess.run(["sudo", "-n", "chmod", "777", document_root], capture_output=True)
        subprocess.run(
            ["sudo", "-n", "tee", os.path.join(document_root, "index.html")],
            input=_default_index_html(server_domain), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["sudo", "-n", "/opt/hostpanel/bin/hp-chown", f"{username}:{document_root}"],
            capture_output=True,
        )
        subprocess.run(["sudo", "-n", "chmod", "-R", "755", f"/home/{username}"], capture_output=True)
        logger.info(f"Nginx on_install: public_html created at {document_root}")
    except Exception as e:
        logger.warning(f"Nginx on_install: could not set up public_html for {server_domain}: {e}")

    # Write nginx vhosts — main site + cpanel reverse proxy
    try:
        write_nginx_vhost(server_domain, document_root)
        write_nginx_cpanel_vhost(server_domain)
        logger.info(f"Nginx on_install: vhosts written — {server_domain} and cpanel.{server_domain}")
    except Exception as e:
        logger.warning(f"Nginx on_install: could not write nginx vhosts for {server_domain}: {e}")

    # Register in the domain registry so the panel shows it immediately
    record = {
        "domain_name": server_domain,
        "username": username,
        "document_root": document_root,
        "status": "active",
    }
    existing.append(record)
    _save_domains(existing)
    logger.info(f"Nginx on_install: default domain '{server_domain}' provisioned and registered")


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
