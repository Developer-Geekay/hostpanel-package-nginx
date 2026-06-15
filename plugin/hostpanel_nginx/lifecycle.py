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

    # Create required runtime directories (including nginx temp dirs to satisfy nginx -t)
    for d in ("vhosts", "logs", "proxy_temp", "client_body_temp",
              "fastcgi_temp", "uwsgi_temp", "scgi_temp"):
        os.makedirs(f"{NGINX_DIR}/{d}", exist_ok=True)

    # Copy nginx.conf and mime.types from conf/ (placed by package manager).
    # nginx.conf is always updated so temp path directives stay current.
    conf_src_dir = os.path.join(NGINX_DIR, "conf")
    for fname in ("nginx.conf", "mime.types"):
        src = os.path.join(conf_src_dir, fname)
        dst = os.path.join(NGINX_DIR, fname)
        if not os.path.exists(src):
            continue
        force = fname == "nginx.conf"  # always refresh main conf to pick up new directives
        if force or not os.path.exists(dst):
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
    # Domain provisioning is handled interactively by the panel UI after install.


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

            # Revoke SSL cert — use certbot directly; it handles its own permissions
            try:
                subprocess.run(
                    ["sudo", "certbot", "delete", "--cert-name", domain_name, "--non-interactive"],
                    capture_output=True, text=True, timeout=30
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

    from hostpanel_nginx.domains import write_nginx_cpanel_vhost, VHOSTS_DIR
    provisioned = 0
    for domain_rec in domains:
        domain_name = domain_rec["domain_name"]
        doc_root = domain_rec.get("document_root", f"/home/{domain_rec.get('username', 'web')}/public_html")
        write_nginx_vhost(domain_name, doc_root, https_forced=False, skip_if_exists=True)

        # Detect current HTTPS state from the main vhost to write the correct cpanel vhost
        main_vhost = f"{VHOSTS_DIR}/{domain_name}.conf"
        https_forced = False
        if os.path.exists(main_vhost):
            with open(main_vhost) as f:
                https_forced = "return 301 https://" in f.read()
        cert_path, key_path = _cert_paths_for(domain_name) if https_forced else ("", "")
        write_nginx_cpanel_vhost(domain_name, doc_root,
                                 https_forced=https_forced,
                                 cert_path=cert_path, key_path=key_path)
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
        try:
            subprocess.run(
                ["sudo", "certbot", "delete", "--cert-name", domain_name, "--non-interactive"],
                capture_output=True, text=True, timeout=30
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


def _cert_paths_for(domain: str):
    """Return (cert_path, key_path) for the domain — checks DB, custom certs, and certbot dir."""
    try:
        import sys as _sys
        _backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _backend not in _sys.path:
            _sys.path.insert(0, _backend)
        from modules.ssl.db import get_cert
        cert = get_cert(domain)
        if cert and cert.get("cert_path") and os.path.exists(cert["cert_path"]):
            key = cert["cert_path"].replace("fullchain.pem", "privkey.pem")
            return cert["cert_path"], key
    except Exception:
        pass
    custom_dir = f"/opt/hostpanel/custom-certs/{domain}"
    new_dir    = f"/opt/hostpanel/certs/live/{domain}"
    if os.path.exists(f"{custom_dir}/fullchain.pem"):
        return f"{custom_dir}/fullchain.pem", f"{custom_dir}/privkey.pem"
    if os.path.exists(f"{new_dir}/fullchain.pem"):
        return f"{new_dir}/fullchain.pem", f"{new_dir}/privkey.pem"
    return "", ""


async def on_ssl_force_https(domain: str, enabled: bool, doc_root: str = None, **kwargs):
    """Called by core SSL when force-HTTPS is toggled. Rewrites the nginx vhost and cpanel vhost."""
    from hostpanel_nginx.domains import write_nginx_vhost, write_nginx_cpanel_vhost
    from domain_registry import _load_domains
    if doc_root is None:
        rec = next((d for d in _load_domains() if d["domain_name"] == domain), None)
        if not rec:
            return
        doc_root = rec["document_root"]
    cert_path, key_path = _cert_paths_for(domain)
    try:
        write_nginx_vhost(domain, doc_root, https_forced=enabled,
                          cert_path=cert_path, key_path=key_path)
        write_nginx_cpanel_vhost(domain, doc_root,
                                 https_forced=enabled,
                                 cert_path=cert_path, key_path=key_path)
        logger.info(f"Nginx vhost updated: force-HTTPS={'on' if enabled else 'off'} for {domain} + cpanel")
    except Exception as e:
        logger.warning(f"Could not update nginx vhost for {domain}: {e}")


async def on_ssl_cert_imported(domain: str, cert_dir: str = None, doc_root: str = None, **kwargs):
    """Called by core SSL when a commercial cert is imported. Updates cpanel vhost if HTTPS was already forced."""
    from hostpanel_nginx.domains import write_nginx_vhost, write_nginx_cpanel_vhost, VHOSTS_DIR
    from domain_registry import _load_domains
    if doc_root is None:
        rec = next((d for d in _load_domains() if d["domain_name"] == domain), None)
        if not rec:
            return
        doc_root = rec["document_root"]
    # Only update vhosts if force-HTTPS was already on (main vhost has return 301)
    main_vhost = f"{VHOSTS_DIR}/{domain}.conf"
    https_was_forced = False
    if os.path.exists(main_vhost):
        with open(main_vhost) as f:
            https_was_forced = "return 301 https://" in f.read()
    if https_was_forced:
        cert_path, key_path = _cert_paths_for(domain)
        try:
            write_nginx_vhost(domain, doc_root, https_forced=True,
                              cert_path=cert_path, key_path=key_path)
            write_nginx_cpanel_vhost(domain, doc_root,
                                     https_forced=True,
                                     cert_path=cert_path, key_path=key_path)
            logger.info(f"Nginx vhosts updated after cert import for {domain}")
        except Exception as e:
            logger.warning(f"Could not update nginx vhost after cert import for {domain}: {e}")


async def on_ssl_cert_deleted(domain: str, doc_root: str = None, **kwargs):
    """Called by core SSL when a cert is deleted. Downgrades nginx vhost and cpanel vhost to plain HTTP."""
    from hostpanel_nginx.domains import write_nginx_vhost, write_nginx_cpanel_vhost
    from domain_registry import _load_domains
    if doc_root is None:
        rec = next((d for d in _load_domains() if d["domain_name"] == domain), None)
        if not rec:
            return
        doc_root = rec["document_root"]
    try:
        write_nginx_vhost(domain, doc_root, https_forced=False)
        write_nginx_cpanel_vhost(domain, doc_root, https_forced=False)
        logger.info(f"Nginx vhosts downgraded to HTTP after cert deletion for {domain} + cpanel")
    except Exception as e:
        logger.warning(f"Could not downgrade nginx vhost for {domain}: {e}")
