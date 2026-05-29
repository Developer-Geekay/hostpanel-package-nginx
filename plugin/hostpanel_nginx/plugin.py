from hostpanel_nginx.domains import router as domains_router
from hostpanel_nginx.redirects import router as redirects_router

PLUGIN_MANIFEST = {
    "requires_core": [1, 0, 0],
    "needs_provisioning": True,
    "nav_items": [
        {
            "nav_route":         "nginx",
            "nav_label":         "Web Server",
            "nav_icon":          "language",
            "nav_section":       "hosting",
            "nav_section_label": "Hosting",
            "nav_section_order": 10,
            "admin_only":        True,
        },
    ],
    "service": {
        "name":       "nginx",
        "unit":       "hostpanel-nginx",
        "label":      "Web Server",
        "icon":       "public",
        "can_reload": True,
    },
}

routers = [domains_router, redirects_router]
