FROM mirror.gcr.io/library/node:24.15.0-bookworm-slim@sha256:4e6b70dd6cbfc88c8157ba19aa3d9f9cce6ba4703576d55459e45efcbc9c5f5d AS build
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/index.html apps/web/tsconfig.json apps/web/vite.config.ts ./
COPY apps/web/src ./src
RUN npm run build

FROM build AS test
COPY apps/web/eslint.config.js apps/web/.prettierrc.json apps/web/.prettierignore ./
RUN chown -R 1000:1000 /app
USER 1000:1000
CMD ["sh", "-c", "npm run lint && npm run typecheck && npm test && npm run build"]

FROM ghcr.io/nginxinc/nginx-unprivileged:stable-alpine@sha256:c715a16970095e90787b02edd68b6371e24c18b8cc905ab1cd17cb20f79816fe
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
COPY LICENSE /usr/share/nginx/html/LICENSE.txt
USER 101:101
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --retries=12 CMD wget -q -O /dev/null http://127.0.0.1:8080/health || exit 1
