FROM mirror.gcr.io/library/caddy:2-alpine@sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648
RUN mkdir -p /data /config && chown -R 10001:10001 /data /config
COPY docker/Caddyfile /etc/caddy/Caddyfile
USER 10001:10001
