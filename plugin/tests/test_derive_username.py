"""Unit tests for _derive_username in hostpanel-package-nginx.
"""
from hostpanel_nginx.domains import _derive_username


def test_derive_username_standard_domain():
    assert _derive_username("example.com") == "example"
    assert _derive_username("mycompany.org") == "mycompany"


def test_derive_username_subdomain_returns_main_domain_label():
    assert _derive_username("sample.example.com") == "example"
    assert _derive_username("dev.api.example.com") == "example"
    assert _derive_username("stage.test.app.internal.org") == "internal"


def test_derive_username_single_label_or_empty():
    assert _derive_username("localhost") == "localhost"
    assert _derive_username("") == "web"
