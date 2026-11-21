# resticprofile 备份 runner 镜像。
# 官方镜像只含 restic / rclone / resticprofile，不含 supercronic；
# 上游文档的容器调度模式就是在此基础上自行派生镜像加 supercronic 做前台调度。
# supercronic 的版本由同目录 mise.toml + mise.lock 锁定：构建时在 mise-tools 阶段
# 安装并校验，最终镜像只接收静态二进制，mise 本体不进入镜像。
# rclone 使用上游镜像自带版本，不由 mise 覆盖。
# 消费方：services 仓库的 edge/resticprofile 与 stump/backup-ops。
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
    && cp "$(mise which supercronic)" /out/supercronic \
    && cp "$(mise which jq)" /out/jq

FROM creativeprojects/resticprofile:0.35.0@sha256:188ba0f18cf710459de0f2780bcf1df9d454689f69de479ffb79f7f4ff8c7569 AS final

COPY --from=mise-tools /out/supercronic /usr/local/bin/supercronic
COPY --from=mise-tools /out/jq /usr/local/bin/jq
