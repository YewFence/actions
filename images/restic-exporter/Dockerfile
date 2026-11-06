# restic-exporter 中心观测镜像。
# 官方镜像（ngosang/restic-exporter）不含 rclone，无法消费 rclone 后端的 restic 仓库；
# rclone 的版本由同目录 mise.toml + mise.lock 锁定：构建时在 mise-tools 阶段安装，
# 最终镜像只接收一个静态二进制，mise 本体不进入镜像。
# 消费方：services 仓库的 stump/backup-ops。
FROM alpine:3.24@sha256:3f4d6b32e26703c6082839234f43769d5046b3ac7c910033911d1e71d8cd630a AS mise-tools
COPY --from=ghcr.io/jdx/mise:2026.11.3@sha256:60a4852b1632aebb032c94bfbaf8196a1088c091bfd6cfa1ce8f182ab39c7d8e /usr/local/bin/mise /usr/local/bin/mise
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
