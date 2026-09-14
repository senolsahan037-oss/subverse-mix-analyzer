from __future__ import annotations

from types import SimpleNamespace

from subverse.access import client_ip, is_admin_claims
from subverse.cloud_uploads import clean_filename


def test_client_ip_prefers_cloud_forwarded_address() -> None:
    request = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.9, 35.191.0.1"},
        client=SimpleNamespace(host="127.0.0.1"),
    )
    assert client_ip(request) == "203.0.113.9"


def test_uploaded_filename_is_reduced_to_a_safe_basename() -> None:
    assert clean_filename("../../My <Mix>.wav") == "My _Mix_.wav"


def test_admin_claims_bypass_product_quota() -> None:
    assert is_admin_claims({"admin": True}) is True
    assert is_admin_claims({"role": "admin"}) is True
    assert is_admin_claims({"admin": False, "email": "member@example.com"}) is False
