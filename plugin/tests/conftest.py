"""Test scaffolding for hostpanel_nginx plugin.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

PLUGIN_DIR = str(Path(__file__).resolve().parent.parent)
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

if "domain_registry" not in sys.modules:
    registry = types.ModuleType("domain_registry")
    registry._load_domains = lambda: []
    registry._load_subdomains = lambda: []
    registry._save_domains = lambda d: None
    registry._save_subdomains = lambda s: None
    registry.check_domain_access = lambda record, user: None
    sys.modules["domain_registry"] = registry

if "auth" not in sys.modules:
    auth_mod = types.ModuleType("auth")
    class _User:
        def __init__(self, username="admin", role="admin", linux_user="admin"):
            self.username = username
            self.role = role
            self.linux_user = linux_user
    auth_mod.User = _User
    sys.modules["auth"] = auth_mod

if "deps" not in sys.modules:
    deps_mod = types.ModuleType("deps")
    deps_mod.get_current_user = lambda: None
    deps_mod.require_admin = lambda: None
    sys.modules["deps"] = deps_mod

if "modules.audit.logger" not in sys.modules:
    audit_mod = types.ModuleType("modules.audit.logger")
    audit_mod.log_action = lambda *args, **kwargs: None
    sys.modules["modules.audit.logger"] = audit_mod
