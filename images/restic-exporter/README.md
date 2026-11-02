# restic-exporter

在 `ngosang/restic-exporter` 官方镜像上注入 rclone 的派生镜像，供 services 仓库 `stump/backup-ops` 的中心 exporter 消费（共享 restic 仓库走 rclone 后端）。

rclone 版本由同目录 `mise.toml` + `mise.lock` 锁定，与 `resticprofile-runner` 保持一致；构建时经 mise 安装，mise 本体不进入最终镜像。

## 更新

- rclone 版本：改 `mise.toml` 后在本目录运行 `mise lock`，与 `resticprofile-runner` 同步评审。
- 上游 exporter 版本：改 `Dockerfile` 的 `FROM` tag 与 digest（digest 用 services 仓库的 `mise run images:resolve-digest` 解析）。
- 合入 main 后由 `build-images` 工作流发布 `ghcr.io/yewfence/restic-exporter:latest` 和从 Dockerfile 最终基础镜像读取的上游版本 tag；两者指向同一个多平台 manifest。
- 镜像的 OCI version label 记录上游版本，revision label 记录实际构建的本仓库完整提交 SHA。版本 tag 会随同版本派生构建更新，需要固定产物时使用 digest。
