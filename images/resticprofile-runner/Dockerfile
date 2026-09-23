# resticprofile 备份 runner 镜像。
# 官方镜像只含 restic / rclone / resticprofile，不含 supercronic；
# 上游文档的容器调度模式就是在此基础上自行派生镜像加 supercronic 做前台调度。
# supercronic 的版本由同目录 mise.toml + mise.lock 锁定：构建时在 mise-tools 阶段
# 安装并校验，最终镜像只接收静态二进制，mise 本体不进入镜像。
# rclone 使用上游镜像自带版本，不由 mise 覆盖。
# 消费方：services 仓库的 edge/resticprofile 与 stump/backup-ops。
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
    && cp "$(mise which supercronic)" /out/supercronic

FROM creativeprojects/resticprofile:0.33.1@sha256:c8afc532eb7693908ca8f0f0a791f632098268ec8ab1b4b63af1a642894a6ad7 AS final

COPY --from=mise-tools /out/supercronic /usr/local/bin/supercronic
