# hostpanel-nginx

Web hosting plugin for [HostPanel](https://github.com/Developer-Geekay/hostpanel).

Manages Nginx virtual hosts — add domains and subdomains, configure redirects, and toggle force-HTTPS. Built on a custom Nginx build at `/opt/hostpanel/nginx/`.

## Requirements

- HostPanel core installed (`setup.sh` completed)
- Nginx built at `/opt/hostpanel/nginx/` (installed by the plugin's `on_install` hook)

## Install

From the HostPanel Package Manager UI, or manually:

```bash
pip install git+https://github.com/Developer-Geekay/hostpanel-package-nginx.git
sudo systemctl restart hostpanel-api
```

## What it provides

| Nav | Route | Description |
|---|---|---|
| Domains | `/dashboard/domains` | Add/remove domains and subdomains, Nginx vhost provisioning |
| Redirects | `/dashboard/redirects` | 301/302 redirect rules per domain |

API prefixes: `/cpanelapi/domains/`, `/cpanelapi/redirects/`

### VHost-only creation

The **+ VHost Only** button (and `POST /cpanelapi/domains/vhost-only`) writes *only* the nginx
server block for a domain — no tenant Linux user, no `public_html`, and no DNS zone. The operator
supplies the `document_root` (static) or `proxy_pass` (proxy) and owns DNS, the document root, and
TLS. The supplied root is validated (absolute path, safe characters) before it is written into nginx
config.

The host is registered as **config-only** (`vhost_only=1` in the `domains` table), so it appears in
the Virtual Hosts list (viewable/editable/deletable, shown with a `config` badge) — but the SSL tab
**skips `vhost_only` domains**, so it never creates a phantom SSL entry (a config-only host has no
DNS zone and can't get a DNS-01 cert). Re-submitting a domain whose `.conf` was created by an older,
unregistered build adopts it into the registry. This is a separate path from **+ Add VHost** (full
provisioning), which is unchanged.

The **+ VHost Only** form has no HTTPS toggle (you own TLS — add a `listen 443 ssl` block in the
raw config editor). Because the panel doesn't track TLS for these hosts, config-only rows show
`Config-only` in the list (not `HTTP`/`HTTPS`) and `Managed in config` for HTTPS in the detail
view, rather than a misleading `HTTP`/`Disabled`.

> Requires core ≥ 1.1.2 (the `domains.vhost_only` column and the SSL-list filter).

## Entry points

| Group | Name | Points to |
|---|---|---|
| `hostpanel.modules` | `nginx` | `hostpanel_nginx.plugin` |
| `hostpanel.lifecycle` | `hostpanel-nginx` | `hostpanel_nginx.lifecycle:pre_uninstall` |
| `hostpanel.hooks.user_delete` | `hostpanel-nginx` | `hostpanel_nginx.lifecycle:on_user_delete` |
| `hostpanel.hooks.domain_delete` | `hostpanel-nginx` | `hostpanel_nginx.lifecycle:on_domain_delete` |
| `hostpanel.hooks.ssl_force_https` | `hostpanel-nginx` | `hostpanel_nginx.lifecycle:on_ssl_force_https` |
| `hostpanel.hooks.ssl_cert_deleted` | `hostpanel-nginx` | `hostpanel_nginx.lifecycle:on_ssl_cert_deleted` |
| `hostpanel.hooks.on_startup` | `hostpanel-nginx` | `hostpanel_nginx.lifecycle:on_startup` |

## Development

```bash
git clone https://github.com/Developer-Geekay/hostpanel-package-nginx.git
cd hostpanel-package-nginx
pip install -e .
```

## License

MIT
