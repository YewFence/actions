# resticprofile 备份 runner 镜像。
# 官方镜像只含 restic / rclone / resticprofile，不含 supercronic；
# 上游文档的容器调度模式就是在此基础上自行派生镜像加 supercronic 做前台调度。
# supercronic 的版本由同目录 mise.toml + mise.lock 锁定：构建时在 mise-tools 阶段
# 安装并校验，最终镜像只接收静态二进制，mise 本体不进入镜像。
# rclone 使用上游镜像自带版本，不由 mise 覆盖。
# 消费方：services 仓库的 edge/resticprofile 与 stump/backup-ops。
FROM alpine:3.24@sha256:f59abe656b692d901e184be3445e084786602108599d2a51d229c0f5a48c71bf AS mise-tools
COPY --from=ghcr.io/jdx/mise:2026.11.6@sha256:d4de1845114f6d73e90e15f7642885f74f3ca93074491038a2b9c43e4b897f21 /usr/local/bin/mise /usr/local/bin/mise
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
    && cp "$(mise which supercronic)" /out/supercronic \
    && cp "$(mise which jq)" /out/jq

FROM creativeprojects/resticprofile:0.33.1@sha256:b919f7ae7adfa4b0900ac87ab5314fb88229698b0a8d38ebc3882a27ac9e73d1 AS final

COPY --from=mise-tools /out/supercronic /usr/local/bin/supercronic
COPY --from=mise-tools /out/jq /usr/local/bin/jq
