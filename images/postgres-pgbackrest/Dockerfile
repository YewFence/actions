# PostgreSQL + pgBackRest + supercronic 运行镜像。
# 官方 postgres 镜像不含 pgbackrest；pgBackRest 是推模式（archive_command 在
# PG 主机本地执行 archive-push），二进制必须随 PG 同容器分发，deb 取自 pgdg 源。
# supercronic 供同 stack 的 sidecar 服务做 cron 调度（backup/expire/check），
# 版本由同目录 mise.toml + mise.lock 锁定：构建时在 mise-tools 阶段安装，
# 最终镜像只接收静态二进制，mise 本体不进入镜像。
# 一个镜像两个角色：postgres 主服务本体（官方 ENTRYPOINT 不变）与
# pgbackrest sidecar（entrypoint 覆盖为 supercronic）。
# 消费方：services 仓库的 edge/postgres。
FROM postgres:18.6@sha256:bd5dfa494a5a259704365813dbfa5fa6b3e69be7348d43b547f540c730478583 AS base

# pgdg 源：手动导入签名 key 并写入 sources.list（与已验证的 barman 镜像同模式）；
# postgres:18.6 基础镜像不含 curl/gnupg，需先安装。
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      | gpg --dearmor -o /usr/share/keyrings/postgresql-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/postgresql-keyring.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
    && rm -rf /var/lib/apt/lists/*

# renovate: datasource=deb depName=pgbackrest registryUrls=http://apt.postgresql.org/pub/repos/apt
# suite 由版本后缀（pgdg12+1）自述，不单独声明。
RUN apt-get update \
    && apt-get install -y --no-install-recommends pgbackrest=2.60.0-1.pgdg12+1 \
    && rm -rf /var/lib/apt/lists/*

FROM alpine:3.24@sha256:be2656061b536c1883c4034790e21d0a09c5aaaf51968b89368a3c0371ea2c9a AS mise-tools
COPY --from=ghcr.io/jdx/mise:2026.11.0@sha256:6e05da4113a812cc8ac72b21a38889d019fb0f97df6ce8075c0de98d1cf48cc4 /usr/local/bin/mise /usr/local/bin/mise
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

FROM base
COPY --from=mise-tools /out/supercronic /usr/local/bin/supercronic
