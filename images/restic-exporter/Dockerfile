# restic-exporter 中心观测镜像。
# 官方镜像（ngosang/restic-exporter）不含 rclone，无法消费 rclone 后端的 restic 仓库；
# rclone 的版本由同目录 mise.toml + mise.lock 锁定：构建时在 mise-tools 阶段安装，
# 最终镜像只接收一个静态二进制，mise 本体不进入镜像。
# 消费方：services 仓库的 stump/backup-ops。
FROM alpine:3.24@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6 AS mise-tools
COPY --from=ghcr.io/jdx/mise:2026.9.12@sha256:868b004119abb2e7c146618da63371ec65da40bfb0f38a0ec4128ca9e96c057a /usr/local/bin/mise /usr/local/bin/mise
# ca-certificates 的版本随 digest 锁定的 alpine 基础镜像走，无需单独 pin
# hadolint ignore=DL3018
RUN apk add --no-cache ca-certificates

ENV MISE_DATA_DIR=/mise \
    MISE_CONFIG_DIR=/mise \
    MISE_CACHE_DIR=/mise/cache
WORKDIR /app
COPY mise.toml mise.lock ./
RUN mise trust \
    && mise install --locked \
    && mkdir /out \
    && cp "$(mise which rclone)" /out/rclone

FROM ngosang/restic-exporter:2.1.2@sha256:a8f9cfa3016237c7008aefa4d9c6639bc9b34d2582eed07ac58dcf56632e4170 AS final

# /usr/local/bin 在 python 基础镜像 PATH 的最前，rclone 开箱即用。
COPY --from=mise-tools /out/rclone /usr/local/bin/rclone
