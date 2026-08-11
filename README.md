# GitHub Actions Collection

这里放一些我自己会用到的 GitHub Actions 工作流。

这个仓库后续可能会继续加入别的零散自动化任务，所以每个工作流都会尽量独立配置，避免互相影响。

## 设计文档

- [声明式容器镜像编排器](docs/container-image-orchestrator.md)

## Rewrite Infisical History

工作流文件在 `.github/workflows/rewrite-infisical-history.yml`。

它每天自动运行一次，也可以在 GitHub Actions 页面手动触发。运行时会克隆 `github.com/infisical/infisical` 的 `main` 分支最近 100 个提交和对应 tags，安装 Rust 与 `filter-repo-rs`，从历史记录里移除整个 `docs` 和 `.github` 目录，然后把重写后的分支和相关 tags 强制推送到你指定的目标远端。

### 需要配置的变量

`TARGET_REMOTE_URL` 可以放在 repository variables 或 repository secrets 里，值是目标仓库的 HTTPS 地址，例如 `https://github.com/example/example.git`。

`TARGET_REMOTE_BRANCH` 可以放在 repository variables 或 repository secrets 里，值是要推送到的目标分支名，例如 `main`。

`GIT_USER_NAME` 可以放在 repository variables 或 repository secrets 里，值是 Git 提交身份里的用户名，不配置时会使用 `github-actions[bot]`。

`GIT_USER_EMAIL` 可以放在 repository variables 或 repository secrets 里，值是 Git 提交身份里的邮箱，不配置时会使用 `41898282+github-actions[bot]@users.noreply.github.com`。

### 需要配置的 secrets

`TARGET_REMOTE_USERNAME` 是目标远端的 HTTPS 用户名。

`TARGET_REMOTE_PASSWORD` 是目标远端的 HTTPS 密码或 token。

这个工作流不会使用 SSH，所以目标远端认证必须能通过 HTTPS 用户名和密码或 token 完成。

### 推送行为

目标分支会被 `git push --force` 覆盖。

tags 只会推送当前浅克隆历史里能关联到 `HEAD` 祖先提交，并且名称符合 `vX.Y.Z` 格式的正式版本 tags，所以 nightly 之类的 tags 不会被推送，并且这些正式版本 tags 也会使用强制推送。

如果目标远端里有重要内容，先确认目标分支和 tags 可以被覆盖。
