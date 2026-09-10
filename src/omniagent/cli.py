"""Reproducible local administration; never exposed as an Agent tool."""

import argparse
import json
import os

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
    parser.add_argument("command", choices=["migrate", "seed", "serve", "mock", "mcp-discover"])
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
    if args.command == "migrate":
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
            print(json.dumps(seed(SessionStore(engine), definitions), ensure_ascii=False))
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
