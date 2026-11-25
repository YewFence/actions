FROM rust:1.100.0-bookworm@sha256:75d26c23c24cc6ea1cdabf0714a6bff8fd7bf3248716043fd7ae86dac7f41b94

RUN apt-get update && apt-get install -y --no-install-recommends cmake libssl-dev pkg-config && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY . .
ARG VERSION
ENV CARGO_INCREMENTAL=0
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/usr/local/cargo/git \
    JOSH_VERSION=${VERSION} cargo build --locked --release -p josh-cli --bin josh --bin josh-filter
RUN mkdir /out && cp target/release/josh target/release/josh-filter LICENSE /out/ \
    && /out/josh --version && /out/josh-filter --help >/dev/null

FROM scratch AS binaries
COPY --from=0 /out/ /
