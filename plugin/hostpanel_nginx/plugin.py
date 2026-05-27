from hostpanel_nginx.domains import router as domains_router
from hostpanel_nginx.redirects import router as redirects_router

PLUGIN_MANIFEST = {
    "requires_core": [1, 0, 0],
    "nav_items": [
        {
            "nav_route":         "domains",
            "nav_label":         "Websites",
            "nav_icon":          "language",
            "nav_section":       "hosting",
            "nav_section_label": "Hosting",
            "nav_section_order": 10,
            "admin_only":        True,
        },
        {
            "nav_route":         "redirects",
            "nav_label":         "Redirects",
            "nav_icon":          "swap_horiz",
            "nav_section":       "hosting",
            "nav_section_label": "Hosting",
            "nav_section_order": 10,
            "admin_only":        True,
        },
    ],
    "service": {
        "name": "nginx",
        "unit": "hostpanel-nginx",
        "label": "Web Server",
        "icon": "public",
        "can_reload": True,
    },
}

routers = [domains_router, redirects_router]
