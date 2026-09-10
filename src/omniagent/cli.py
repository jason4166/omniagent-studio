"""Reproducible local administration; never exposed as an Agent tool."""

import argparse
import json
import os
from pathlib import Path

from alembic import command
from alembic.config import Config

from omniagent.application import DEFAULT_DATABASE_URL
from omniagent.checkpoints import migrate_checkpoints
from omniagent.connectors import catalog
from omniagent.database import build_engine
from omniagent.mcp_tools import MCPToolAdapter
from omniagent.presets import seed
from omniagent.session_store import SessionStore


def main() -> None:
    parser = argparse.ArgumentParser(prog="omniagent")
    parser.add_argument(
        "command",
        choices=[
            "migrate",
            "seed",
            "serve",
            "mock",
            "mcp-discover",
            "eval",
            "compare",
            "security",
            "benchmark",
            "eval-real",
            "purge",
        ],
    )
    parser.add_argument("--output", type=Path, default=Path(".pytest-tmp-reports"))
    parser.add_argument("--variant", default="candidate")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        choices=[
            "127.0.0.1",
            "0.0.0.0",  # noqa: S104 - explicit container binding option
        ],
    )
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    url = os.environ.get("OMNIAGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
    if args.command == "purge":
        from omniagent.maintenance import purge

        print(json.dumps(purge(url)))
    elif args.command == "eval-real":
        from omniagent.real_baseline import real_baseline

        real = real_baseline(url, args.output, variant=args.variant)
        print(json.dumps({"metrics": real.metrics, "safety_gates": real.safety_gates}))
        raise SystemExit(
            0
            if all(real.safety_gates.values()) and all(row.e2e_success for row in real.results)
            else 1
        )
    elif args.command == "eval":
        from omniagent.eval_platform import evaluate
        from omniagent.quality_gates import eval_passes

        result = evaluate(url, args.output, variant=args.variant)
        print(
            json.dumps(
                {"metrics": result.metrics, "safety_gates": result.safety_gates}, ensure_ascii=False
            )
        )
        raise SystemExit(0 if eval_passes(result) else 1)
    elif args.command == "compare":
        from omniagent.quality_gates import compare

        if args.baseline is None or args.candidate is None:
            parser.error("--baseline and --candidate are required for comparison")
        print(json.dumps(compare(args.baseline, args.candidate, args.output)))
    elif args.command == "security":
        from omniagent.quality_gates import security_gate

        security = security_gate(Path.cwd(), args.output, url)
        print(json.dumps(security))
        raise SystemExit(0 if security["passed"] else 1)
    elif args.command == "benchmark":
        from omniagent.benchmark import benchmark

        report = benchmark(url, args.output, variant=args.variant)
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in ("p50_ms", "p95_ms", "mean_database_queries", "mean_database_ms")
                }
            )
        )
    elif args.command == "migrate":
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        command.upgrade(config, "head")
        migrate_checkpoints(url)
        print("Database and checkpoint migrations complete")
    elif args.command == "seed":
        engine = build_engine(url)
        try:
            definitions, _ = catalog(
                os.environ.get("OMNIAGENT_MOCK_HOST", "127.0.0.1"),
                int(os.environ.get("OMNIAGENT_MOCK_PORT", "18081")),
            )
            print(
                json.dumps(
                    seed(
                        SessionStore(engine),
                        definitions,
                        mode=os.environ.get("OMNIAGENT_RUNTIME_MODE", "fake"),
                    ),
                    ensure_ascii=False,
                )
            )
        finally:
            engine.dispose()
    elif args.command == "mcp-discover":
        print(json.dumps(MCPToolAdapter().discover(), ensure_ascii=False))
    else:
        import uvicorn

        module = (
            "omniagent.application:create_app"
            if args.command == "serve"
            else "omniagent.mock_service:create_mock_app"
        )
        uvicorn.run(
            module,
            factory=True,
            host=args.host,
            port=args.port or (18080 if args.command == "serve" else 18081),
            access_log=False,
        )


if __name__ == "__main__":
    main()
