# restic-exporter 中心观测镜像。
# 官方镜像（ngosang/restic-exporter）不含 rclone，无法消费 rclone 后端的 restic 仓库；
# rclone 的版本由同目录 mise.toml + mise.lock 锁定：构建时在 mise-tools 阶段安装，
# 最终镜像只接收一个静态二进制，mise 本体不进入镜像。
# 消费方：services 仓库的 stump/backup-ops。
FROM alpine:3.24@sha256:f59abe656b692d901e184be3445e084786602108599d2a51d229c0f5a48c71bf AS mise-tools
COPY --from=ghcr.io/jdx/mise:2026.11.12@sha256:991e2a550518ec5cae6f25adbc862ec0253ff714ee6e5e6bf328058a7324a041 /usr/local/bin/mise /usr/local/bin/mise
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

FROM ngosang/restic-exporter:2.2.1@sha256:d52129303925520186bf17ffa0389ba56a1651afbc1c4bc5ce12ed6543d33192 AS final

# /usr/local/bin 在 python 基础镜像 PATH 的最前，rclone 开箱即用。
COPY --from=mise-tools /out/rclone /usr/local/bin/rclone
