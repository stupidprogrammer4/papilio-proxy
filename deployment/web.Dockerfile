ARG NODE_IMAGE=node:22-bookworm-slim
ARG CADDY_IMAGE=caddy:2.10
FROM ${NODE_IMAGE} AS build
WORKDIR /build
RUN npm install --global pnpm@9.15.9
COPY panel/frontend/package.json panel/frontend/pnpm-lock.yaml panel/frontend/pnpm-workspace.yaml ./
COPY panel/frontend/packages ./packages
COPY panel/frontend/apps ./apps
RUN pnpm install --frozen-lockfile
ENV PAPILIO_BACKEND_URL=http://api:8000 PAPILIO_PANEL_PORT=8080
RUN pnpm build
FROM ${CADDY_IMAGE}
COPY --from=build /build/apps/panel/dist /srv
