FROM golang:1.26-bookworm AS toolchain

FROM python:3.13-slim-bookworm AS build
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=toolchain /usr/local/go /usr/local/go
ARG PAPILIO_GO_PROXY=https://proxy.golang.org|direct
ENV PATH="/usr/local/go/bin:${PATH}" GOTOOLCHAIN=local PYTHONDONTWRITEBYTECODE=1 GOPROXY=${PAPILIO_GO_PROXY}
WORKDIR /source
COPY VERSION LICENSE ./
COPY node/agent/go.mod node/agent/go.sum ./node/agent/
COPY node/agent/cmd ./node/agent/cmd
COPY node/agent/internal ./node/agent/internal
COPY deployment/build_node.py ./deployment/
COPY deployment/papilio_installer/__init__.py deployment/papilio_installer/releases.py ./deployment/papilio_installer/
COPY deployment/papilio_installer/node ./deployment/papilio_installer/node
RUN --mount=type=cache,target=/root/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/tmp/node-cache \
    python deployment/build_node.py --output /tmp/node-assets --cache /tmp/node-cache
RUN mkdir /tmp/node-runtime \
    && tar -xzf /tmp/node-assets/papilio-node-*-linux-*.tar.gz -C /tmp/node-runtime

FROM debian:bookworm-slim
RUN groupadd --gid 10001 papilio \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin papilio \
    && install -d -o 10001 -g 10001 -m 0700 /var/lib/papilio/local-node
COPY --from=build /tmp/node-runtime/bin/ /usr/local/bin/
COPY --from=build /tmp/node-runtime/licenses/ /usr/share/doc/papilio-node/
USER 10001:10001
ENTRYPOINT ["/usr/local/bin/papilio-agent"]
CMD ["-config", "/var/lib/papilio/local-node/instance/agent.json", "-wait-for-config"]
