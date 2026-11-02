# resticprofile 备份 runner 镜像。
# 官方镜像只含 restic / rclone / resticprofile，不含 supercronic；
# 上游文档的容器调度模式就是在此基础上自行派生镜像加 supercronic 做前台调度。
# supercronic 的版本由同目录 mise.toml + mise.lock 锁定：构建时在 mise-tools 阶段
# 安装并校验，最终镜像只接收静态二进制，mise 本体不进入镜像。
# rclone 使用上游镜像自带版本，不由 mise 覆盖。
# 消费方：services 仓库的 edge/resticprofile 与 stump/backup-ops。
FROM alpine:3.24@sha256:be2656061b536c1883c4034790e21d0a09c5aaaf51968b89368a3c0371ea2c9a AS mise-tools
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
    && cp "$(mise which supercronic)" /out/supercronic \
    && cp "$(mise which jq)" /out/jq

FROM creativeprojects/resticprofile:0.33.1@sha256:11ecefbac151a2e9c2929a0190fde91f5f750f6c3a3f529dd708043d51d92414 AS final

COPY --from=mise-tools /out/supercronic /usr/local/bin/supercronic
COPY --from=mise-tools /out/jq /usr/local/bin/jq
