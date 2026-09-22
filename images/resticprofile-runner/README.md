# resticprofile-runner

在 `creativeprojects/resticprofile` 官方镜像上加 `supercronic` 的薄派生镜像，用于 services 仓库的声明式 restic 备份链路（`edge/resticprofile` 上传 runner、`stump/backup-ops` 维护 runner）。

官方镜像只提供 restic、rclone 和 resticprofile；resticprofile 自身没有前台调度模式，上游文档的容器调度方案就是派生镜像 + supercronic（见上游 `non-root-schedule-in-container` 文档）。

## 更新

- Renovate（`renovate.json` 的 docker manager）自动维护 `Dockerfile` 的 `FROM` tag 与 digest：上游发版或重推同 tag 时开 PR。
- 合入 main 后由 `build-images` 工作流发布为 `ghcr.io/yewfence/resticprofile-runner:latest`（多平台 manifest）。
