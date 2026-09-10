"""Strict checkpoint serialization and explicit storage migration."""

from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import Connection
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url


@contextmanager
def postgres_saver(database_url: str) -> Iterator[PostgresSaver]:
    url = make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)
    with Connection.connect(
        url,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        connect_timeout=5,
        options="-c statement_timeout=10000",
    ) as connection:
        yield PostgresSaver(
            connection,
            serde=JsonPlusSerializer(
                pickle_fallback=False,
                allowed_json_modules=[],
                allowed_msgpack_modules=[],
            ),
        )


def migrate_checkpoints(database_url: str) -> None:
    with postgres_saver(database_url) as saver:
        saver.setup()
