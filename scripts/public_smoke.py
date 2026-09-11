"""Authenticate actual TLS, cookie and multi-user boundaries without exposing credentials."""

import argparse
import json
import ssl
from pathlib import Path
from uuid import uuid4

import httpx
from ops import ROOT, compose_arguments


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    compose_arguments(args.project)
    private = ROOT / ".local" / "deployments" / args.project
    metadata = json.loads((private / "deployment.json").read_text(encoding="utf-8"))
    origin = metadata["origin"]
    require(
        origin.startswith("https://") and metadata["environment"] == "production",
        "HTTPS production configuration required",
    )
    context = ssl.create_default_context(cafile=str(args.ca_file) if args.ca_file else None)
    account = json.loads((private / "admin.json").read_text(encoding="utf-8"))
    owned = []
    clients = []
    thread = None
    report: dict[str, object] = {"passed": False, "scope": "TLS and application access boundaries"}
    with httpx.Client(
        base_url=origin, verify=context, headers={"Origin": origin}, timeout=20
    ) as admin:

        def login(client, username, password):
            response = client.post(
                "/api/auth/login", json={"username": username, "password": password}
            )
            response.raise_for_status()
            client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
            return response

        try:
            require(admin.get("/ready").json()["status"] == "ready", "Readiness")
            require(
                admin.get(
                    "/api/profiles", headers={"Authorization": "Bearer local-demo-admin"}
                ).status_code
                == 401,
                "Demo token accepted",
            )
            response = login(admin, account["username"], account["password"])
            cookie = response.headers["set-cookie"].lower()
            require(
                all(
                    value in cookie
                    for value in [
                        "__host-omniagent_session",
                        "httponly",
                        "secure",
                        "samesite=strict",
                    ]
                ),
                "Cookie flags",
            )
            require(
                admin.get("/ready").headers.get("strict-transport-security") == "max-age=31536000",
                "HSTS",
            )
            require(
                admin.post(
                    "/api/sessions", json={"profile_id": "hr"}, headers={"X-CSRF-Token": ""}
                ).status_code
                == 403,
                "CSRF missing",
            )
            require(
                admin.post(
                    "/api/sessions",
                    json={"profile_id": "hr"},
                    headers={"Origin": "https://attacker.example"},
                ).status_code
                == 403,
                "Origin mismatch",
            )
            require(
                admin.get("/docs").status_code == 404
                and admin.get("/openapi.json").status_code == 404,
                "Public API documentation",
            )
            report.update(
                tls_verified=True,
                secure_cookie=True,
                csrf_origin=True,
                demo_tokens_rejected=True,
                hsts=True,
                docs_disabled=True,
            )
            for _ in range(2):
                username = "probe-" + uuid4().hex[:12]
                password = uuid4().hex + uuid4().hex
                result = (
                    admin.post(
                        "/api/accounts",
                        json={
                            "username": username,
                            "password": password,
                            "role": "member",
                            "profile_ids": ["hr"],
                        },
                    )
                    .raise_for_status()
                    .json()
                )
                owned.append(result)
                client = httpx.Client(
                    base_url=origin, verify=context, headers={"Origin": origin}, timeout=20
                )
                clients.append(client)
                login(client, username, password)
            alice, bob = clients
            thread = (
                alice.post("/api/sessions", json={"profile_id": "hr"})
                .raise_for_status()
                .json()["thread_id"]
            )
            require(bob.get("/api/sessions").json() == [], "Shared identity")
            for method, suffix in [
                ("GET", ""),
                ("DELETE", ""),
                ("POST", "/cancel"),
                ("GET", "/events?follow=false"),
            ]:
                require(
                    bob.request(method, "/api/sessions/" + thread + suffix).status_code == 404,
                    "Cross-user access",
                )
            require(
                alice.get(
                    "/api/accounts", headers={"Authorization": "Bearer local-demo-admin"}
                ).status_code
                == 403,
                "Role escalation",
            )
            require(
                alice.post("/api/sessions", json={"profile_id": "sales"}).status_code == 403,
                "Profile escalation",
            )
            alice.delete("/api/sessions/" + thread).raise_for_status()
            thread = None
            report.update(user_isolation=True, role_profile_isolation=True)
            first = owned[0]
            admin.put(
                "/api/accounts/" + first["user_id"],
                json={
                    "expected_version": first["version"],
                    "enabled": False,
                    "role": first["role"],
                    "profile_ids": first["profile_ids"],
                },
            ).raise_for_status()
            owned.pop(0)
            require(alice.get("/api/sessions").status_code == 401, "Disabled login remains valid")
            bob.post("/api/auth/logout").raise_for_status()
            require(bob.get("/api/sessions").status_code == 401, "Logout remains valid")
            report.update(revocation=True, passed=True)
        except Exception as exc:
            report["error_type"] = type(exc).__name__
            raise
        finally:
            cleanup_errors = []
            if thread and clients:
                try:
                    clients[0].delete("/api/sessions/" + thread).raise_for_status()
                except Exception as exc:
                    cleanup_errors.append(type(exc).__name__)
            for record in owned:
                try:
                    admin.put(
                        "/api/accounts/" + record["user_id"],
                        json={
                            "expected_version": record["version"],
                            "enabled": False,
                            "role": record["role"],
                            "profile_ids": record["profile_ids"],
                        },
                    ).raise_for_status()
                except Exception as exc:
                    cleanup_errors.append(type(exc).__name__)
            for client in clients:
                client.close()
            try:
                admin.post("/api/auth/logout")
            except Exception as exc:
                cleanup_errors.append(type(exc).__name__)
            report["cleanup_errors"] = cleanup_errors
            if cleanup_errors:
                report["passed"] = False
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / "public-smoke.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
            if cleanup_errors:
                raise RuntimeError("Cleanup failed; the failure report was preserved")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
