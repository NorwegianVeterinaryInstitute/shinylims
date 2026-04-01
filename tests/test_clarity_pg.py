from __future__ import annotations

from sqlalchemy.engine.url import make_url

from shinylims.integrations import clarity_pg
from shinylims.integrations.clarity_pg import ClarityPostgresConfig, get_clarity_pg_ssl_diagnostics


def test_sqlalchemy_url_includes_ssl_query_parameters():
    config = ClarityPostgresConfig(
        database="clarity",
        username="reader",
        password="secret",
        host="db.example.org",
        port=5432,
        sslmode="require",
        sslrootcert="/etc/ssl/root.crt",
    )

    url = make_url(str(config.sqlalchemy_url()))

    assert url.query["sslmode"] == "require"
    assert url.query["sslrootcert"] == "/etc/ssl/root.crt"


def test_sqlalchemy_url_preserves_explicit_sslmode_from_clarity_pg_url():
    config = ClarityPostgresConfig(
        database="",
        username="",
        password="",
        url="postgresql+psycopg://reader:secret@db.example.org:5432/clarity?sslmode=verify-full",
        sslmode="require",
        sslrootcert="/etc/ssl/root.crt",
    )

    url = make_url(str(config.sqlalchemy_url()))

    assert url.query["sslmode"] == "verify-full"
    assert url.query["sslrootcert"] == "/etc/ssl/root.crt"


def test_get_clarity_pg_ssl_diagnostics_reports_live_session_details(monkeypatch):
    monkeypatch.setenv("CLARITY_PG_SSLMODE", "require")

    class FakeMappings:
        def first(self):
            return {
                "ssl": True,
                "version": "TLSv1.3",
                "cipher": "TLS_AES_256_GCM_SHA384",
                "bits": 256,
                "client_dn": None,
            }

    class FakeResult:
        def mappings(self):
            return FakeMappings()

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement):
            return FakeResult()

    monkeypatch.setattr(clarity_pg, "create_session", lambda: FakeSession())

    diagnostics = get_clarity_pg_ssl_diagnostics()

    assert diagnostics["configured_sslmode"] == "require"
    assert diagnostics["connection_ok"] is True
    assert diagnostics["ssl_status_available"] is True
    assert diagnostics["ssl_in_use"] is True
    assert diagnostics["ssl_version"] == "TLSv1.3"
    assert diagnostics["ssl_cipher"] == "TLS_AES_256_GCM_SHA384"
    assert diagnostics["ssl_bits"] == 256


def test_get_clarity_pg_ssl_diagnostics_reports_connection_errors(monkeypatch):
    monkeypatch.delenv("CLARITY_PG_SSLMODE", raising=False)

    class FailingSession:
        def __enter__(self):
            raise RuntimeError("connection failed")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(clarity_pg, "create_session", lambda: FailingSession())

    diagnostics = get_clarity_pg_ssl_diagnostics()

    assert diagnostics["configured_sslmode"] == "<driver-default>"
    assert diagnostics["connection_ok"] is False
    assert diagnostics["ssl_status_available"] is False
    assert diagnostics["error_type"] == "RuntimeError"
    assert diagnostics["error"] == "connection failed"
