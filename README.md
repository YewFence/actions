# GitHub Actions Collection

这里放一些我自己会用到的 GitHub Actions 工作流。

这个仓库后续可能会继续加入别的零散自动化任务，所以每个工作流都会尽量独立配置，避免互相影响。

## 设计文档

- [声明式容器镜像编排器](docs/container-image-orchestrator.md)
- [Forgejo 默认分支镜像与历史归档](docs/mirror-design.md)
- [Fork Outdated Notifier](docs/fork-outdated-notifier.md)

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

## Fork Outdated Notifier

工作流文件在 `.github/workflows/fork-outdated-notifier.yml`。

它每天自动运行一次，也可以在 GitHub Actions 页面手动触发。运行时会列出当前用户名下所有公开 fork，用 GitHub compare API 比较 fork 默认分支与上游默认分支，把落后于上游的 fork（领先的不会列出）汇总为一条 Telegram 消息发送，并在 Job Summary 中输出完整表格。上游已被删除或不可访问的 fork 不会被误判为 outdated，只会在 Summary 中单独列出。

### 需要配置的 secrets

`TELEGRAM_BOT_TOKEN` 是 Telegram Bot 的 token（向 @BotFather 申请）。

`TELEGRAM_CHAT_ID` 是接收消息的聊天 ID。

两个 Telegram secrets 都是可选的；不配置时只输出 Job Summary，不发送消息。

`FORKS_GH_TOKEN` 是用于调用 GitHub API 的 token（可选）。不配置时使用工作流自动注入的 `GITHUB_TOKEN`；如果 fork 数量较多或希望速率限制更宽松，可以配置一个只需公开仓库只读权限的 PAT。

### 忽略列表

仓库根目录的 `forks-ignore.txt` 每行列出一个不参与检查的仓库，支持 `owner/repo`（推荐）或裸仓库名，`#` 后内容为注释。
