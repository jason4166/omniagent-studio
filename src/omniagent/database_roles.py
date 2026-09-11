"""Migration-only role provisioning; runtime containers cannot administer PostgreSQL."""

from psycopg import connect, sql
from sqlalchemy.engine import make_url

from omniagent.credentials import resolve_credential


def provision_roles(database_url: str) -> None:
    dsn = make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)
    try:
        with connect(dsn, connect_timeout=5, options="-c statement_timeout=10000") as connection:
            for role, reference in [
                ("omniagent_runtime", "OMNIAGENT_RUNTIME_PASSWORD"),
                ("omniagent_mock", "OMNIAGENT_MOCK_PASSWORD"),
            ]:
                password = resolve_credential(reference)
                if len(password) < 24:
                    raise ValueError("Credential must be independently generated")
                if not connection.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)
                ).fetchone():
                    connection.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))
                connection.execute(
                    sql.SQL(
                        "ALTER ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION PASSWORD {}"
                    ).format(sql.Identifier(role), sql.Literal(password))
                )
                connection.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role))
                )
            connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            connection.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
                "TO omniagent_runtime"
            )
            connection.execute(
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO omniagent_runtime"
            )
            connection.execute("REVOKE ALL ON mock_effects FROM omniagent_runtime")
            connection.execute("GRANT SELECT, INSERT, UPDATE ON mock_effects TO omniagent_mock")
            connection.execute("GRANT SELECT ON sessions, approvals TO omniagent_mock")
    except Exception:
        raise SystemExit("Database role provisioning failed") from None
