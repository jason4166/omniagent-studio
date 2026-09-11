FROM mirror.gcr.io/library/python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2 AS dependencies
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=0 UV_PYTHON_DOWNLOADS=never
COPY --from=ghcr.io/astral-sh/uv:0.12.1@sha256:cf4eedcaa81655197f625739489effcbe71b61ceb1506f332c3facae5deceded /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

FROM mirror.gcr.io/library/python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2 AS api
ARG GIT_REVISION=development
RUN groupadd --gid 10001 omniagent && useradd --uid 10001 --gid 10001 --no-create-home omniagent
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV OMNIAGENT_GIT_REVISION=$GIT_REVISION
LABEL org.opencontainers.image.title="OmniAgent Studio" org.opencontainers.image.revision=$GIT_REVISION
COPY --from=dependencies --chown=0:0 /app/.venv /app/.venv
COPY --chown=0:0 src ./src
COPY --chown=0:0 presets ./presets
COPY --chown=0:0 migrations ./migrations
COPY --chown=0:0 alembic.ini LICENSE ./
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --retries=12 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=2).close()"]
CMD ["omniagent", "serve", "--host", "0.0.0.0", "--port", "8000"]

FROM api AS mock
EXPOSE 8081
HEALTHCHECK --interval=5s --timeout=3s --retries=12 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=2).close()"]
CMD ["omniagent", "mock", "--host", "0.0.0.0", "--port", "8081"]

FROM mirror.gcr.io/library/python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2 AS test-tools
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=2 -o Acquire::https::Timeout=30 update \
    && apt-get -o Acquire::Retries=2 -o Acquire::https::Timeout=30 install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.1@sha256:cf4eedcaa81655197f625739489effcbe71b61ceb1506f332c3facae5deceded /uv /usr/local/bin/uv

FROM test-tools AS test
ARG GIT_REVISION=development
WORKDIR /app
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY --from=dependencies /app /app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked && chown -R 10001:10001 /app
COPY --chown=10001:10001 tests ./tests
COPY --chown=10001:10001 evals ./evals
COPY --chown=10001:10001 security ./security
COPY --chown=10001:10001 reliability ./reliability
COPY --chown=10001:10001 scripts/ops.py scripts/private_config.py scripts/acceptance.py scripts/backup.py ./scripts/
COPY --chown=10001:10001 scripts/compare_benchmark.py ./scripts/
COPY --chown=10001:10001 presets ./presets
COPY --chown=10001:10001 migrations ./migrations
COPY --chown=10001:10001 examples ./examples
COPY --chown=10001:10001 alembic.ini ./
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV OMNIAGENT_GIT_REVISION=$GIT_REVISION
USER 10001:10001
CMD ["python", "-m", "pytest", "--basetemp", "/tmp/pytest", "-p", "no:cacheprovider"]
