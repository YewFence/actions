# resticprofile-runner

在 `creativeprojects/resticprofile` 官方镜像上加 `supercronic` 和 `jq` 的薄派生镜像，用于 services 仓库的声明式 restic 备份链路（`edge/resticprofile` 上传 runner、`stump/backup-ops` 维护 runner）。

官方镜像只提供 restic、rclone 和 resticprofile；resticprofile 自身没有前台调度模式，上游文档的容器调度方案就是派生镜像 + supercronic（见上游 `non-root-schedule-in-container` 文档）。

supercronic 与 jq 经 mise 在构建期安装：版本和下载 sha256 由本目录 `mise.toml` + `mise.lock` 锁定；最终镜像只拷贝两个静态二进制到 `/usr/local/bin`，mise 本体不进入镜像。rclone 沿用上游基础镜像自带版本。

## 更新

- Renovate（`renovate.json` 的 docker manager）自动维护 `Dockerfile` 里的 `FROM`/`COPY --from` 镜像 tag 与 digest：上游发版或重推同 tag 时开 PR。
- supercronic / jq 的版本号在 `mise.toml` 里手工升级：改完版本后在本目录运行 `mise lock` 刷新 `mise.lock`（含新版本各平台下载 URL 与 sha256），一起提交。
- 合入 main 后由 `build-images` 工作流发布 `ghcr.io/yewfence/resticprofile-runner:latest` 和从 Dockerfile 最终基础镜像读取的上游版本 tag；两者指向同一个多平台 manifest。
- 镜像的 OCI version label 记录上游版本，revision label 记录实际构建的本仓库完整提交 SHA。版本 tag 会随同版本派生构建更新，需要固定产物时使用 digest。
