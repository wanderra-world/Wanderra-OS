"""Architecture Fitness for the bounded ADR-035 runtime implementation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_adr_035_has_one_decision_and_an_inbound_index_reference() -> None:
    decisions = (ROOT / "DECISIONS.md").read_text()
    index = (ROOT / "README_ARCHITECTURE.md").read_text()

    assert decisions.count("## ADR-035:") == 1
    assert "ADR-035 selects Google Identity" in index
    assert (
        "#adr-035-use-google-identity-as-the-initial-atlas-operator-"
        "authentication-authority"
    ) in index


def test_operator_auth_reuses_canonical_identity_and_session_models() -> None:
    service = (ROOT / "app/identity/operator_auth.py").read_text()
    api = (ROOT / "app/api/v1/operator_auth.py").read_text()

    assert "ExternalIdentityLink.issuer == issuer" in service
    assert "ExternalIdentityLink.subject == subject" in service
    assert "IdentityLifecycleService(self._session).issue_session" in service
    assert "WorkspaceMembershipRepository" in service
    assert 'OPERATOR_LOGIN_PERMISSION = "manage_workspace"' in service
    assert "User.email" not in service
    assert "create_user" not in service
    assert "password" not in service.casefold()
    assert "__Host-atlas_session" in api
    assert "__Host-atlas_csrf" in api
    assert "secure=True" in api
    assert "httponly=True" in api
    assert 'samesite="lax"' in api


def test_google_identity_and_gmail_authorization_remain_separate() -> None:
    oidc = (ROOT / "app/integrations/google_identity/oidc.py").read_text()
    operator_api = (ROOT / "app/api/v1/operator_auth.py").read_text()
    gmail_oauth = (ROOT / "app/integrations/gmail/oauth.py").read_text()

    assert 'IDENTITY_SCOPES = ("openid", "email", "profile")' in oidc
    assert "GMAIL_ALLOWED_SCOPES" not in oidc
    assert "GmailOAuthProtocol" not in operator_api
    assert "openid email profile" not in gmail_oauth
    assert "verify_oauth2_token" in oidc
    assert "code_challenge_method" in oidc
    assert "expected_nonce" in oidc


def test_runtime_slice_adds_no_migration_or_future_provider() -> None:
    revisions = sorted((ROOT / "alembic/versions").glob("*.py"))
    names = {path.name for path in revisions}
    production = "\n".join(
        (ROOT / path).read_text()
        for path in (
            Path("app/integrations/google_identity/oidc.py"),
            Path("app/identity/operator_auth.py"),
            Path("app/api/v1/operator_auth.py"),
        )
    ).casefold()

    assert "0032_add_platform_hardening.py" in names
    assert not any(name.startswith("0033") for name in names)
    for excluded in (
        "calendar",
        "drive",
        "whatsapp",
        "stripe",
        "linkedin",
        "facebook",
        "instagram",
        "tiktok",
        "business agent",
    ):
        assert excluded not in production
