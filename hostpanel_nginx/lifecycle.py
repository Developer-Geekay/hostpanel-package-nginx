import logging
import os
import subprocess

from fastapi import HTTPException

logger = logging.getLogger(__name__)

LETSENCRYPT_DIR = "/etc/letsencrypt/live"


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
        logger.info("Nginx plugin uninstalled: all vhosts and SSL certs removed. DNS zones preserved.")


async def on_startup():
    """Called at server startup. Provisions nginx vhosts for any domains in the
    registry that don't already have a vhost config (e.g. after fresh nginx install)."""
    from domain_registry import _load_domains, _load_subdomains
    from hostpanel_nginx.domains import write_nginx_vhost, VHOSTS_DIR

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
