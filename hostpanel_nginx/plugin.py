from hostpanel_nginx.domains import router as domains_router
from hostpanel_nginx.redirects import router as redirects_router

PLUGIN_MANIFEST = {
    "requires_core": [1, 0, 0],
    "nav_items": [
        {
            "nav_route": "domains",
            "nav_label": "Websites",
            "nav_icon": "language",
            "nav_section": "hosting",
            "admin_only": True,
        },
    ]
}

routers = [domains_router, redirects_router]
