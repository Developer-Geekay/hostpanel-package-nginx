from setuptools import setup, find_packages

setup(
    name="hostpanel-nginx",
    version="1.0.0",
    packages=find_packages(),
    install_requires=["fastapi", "pydantic", "httpx"],
    entry_points={
        "hostpanel.modules": [
            "nginx = hostpanel_nginx.plugin"
        ],
        "hostpanel.lifecycle": [
            "hostpanel-nginx = hostpanel_nginx.lifecycle:pre_uninstall"
        ],
        "hostpanel.hooks.user_delete": [
            "hostpanel-nginx = hostpanel_nginx.lifecycle:on_user_delete"
        ],
        "hostpanel.hooks.domain_delete": [
            "hostpanel-nginx = hostpanel_nginx.lifecycle:on_domain_delete"
        ],
        "hostpanel.hooks.ssl_force_https": [
            "hostpanel-nginx = hostpanel_nginx.lifecycle:on_ssl_force_https"
        ],
        "hostpanel.hooks.ssl_cert_deleted": [
            "hostpanel-nginx = hostpanel_nginx.lifecycle:on_ssl_cert_deleted"
        ],
        "hostpanel.hooks.on_startup": [
            "hostpanel-nginx = hostpanel_nginx.lifecycle:on_startup"
        ],
    }
)
