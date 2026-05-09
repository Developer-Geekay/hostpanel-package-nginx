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
