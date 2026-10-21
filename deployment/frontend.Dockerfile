FROM node:22-bookworm-slim AS build
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate
WORKDIR /source
COPY panel/frontend/package.json panel/frontend/pnpm-lock.yaml panel/frontend/pnpm-workspace.yaml ./
COPY panel/frontend/apps/panel/package.json ./apps/panel/package.json
COPY panel/frontend/packages/api/package.json ./packages/api/package.json
COPY panel/frontend/packages/auth/package.json ./packages/auth/package.json
COPY panel/frontend/packages/ui/package.json ./packages/ui/package.json
RUN pnpm install --frozen-lockfile
COPY panel/frontend/ ./
RUN pnpm build
FROM caddy:2-alpine
COPY deployment/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /source/apps/panel/dist /srv
