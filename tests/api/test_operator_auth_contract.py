"""HTTP contract tests for the bounded ADR-035 operator boundary."""

from __future__ import annotations

from fastapi.routing import APIRoute

from app.api.v1.operator_auth import OperatorSessionResponse, router


def test_operator_auth_routes_are_bounded() -> None:
    routes = {
        route.path: route.methods for route in router.routes if isinstance(route, APIRoute)
    }

    assert routes == {
        "/auth/google/start": {"GET"},
        "/auth/google/callback": {"GET"},
        "/workspaces/{workspace_id}/session/revoke": {"POST"},
    }


def test_operator_session_response_never_contains_cookie_or_provider_secrets() -> None:
    fields = set(OperatorSessionResponse.model_fields)

    assert fields == {
        "workspace_id",
        "user_id",
        "membership_id",
        "session_id",
        "expires_at",
    }
    assert not fields & {
        "access_token",
        "refresh_token",
        "id_token",
        "client_secret",
        "authorization_code",
        "state",
        "nonce",
        "pkce_verifier",
        "raw_session",
        "csrf_token",
    }


def test_operator_cookie_contract_is_secure_httponly_and_samesite() -> None:
    source = (router.routes[0].endpoint.__module__)
    assert source == "app.api.v1.operator_auth"
    implementation = __import__(source, fromlist=["unused"])
    response = __import__("starlette.responses", fromlist=["Response"]).Response()

    implementation._set_host_cookie(
        response,
        key="__Host-test",
        value="opaque-value",
        max_age=600,
    )

    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    deletion = implementation._oidc_cookie_deletion_header()
    assert "Max-Age=0" in deletion
    assert "Secure" in deletion
    assert "HttpOnly" in deletion
