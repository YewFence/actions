# GitHub Actions Collection

这里放一些我自己会用到的 GitHub Actions 工作流。

这个仓库后续可能会继续加入别的零散自动化任务，所以每个工作流都会尽量独立配置，避免互相影响。

## 设计文档

- [声明式容器镜像编排器](docs/container-image-orchestrator.md)
- [Forgejo 默认分支镜像与历史归档](docs/mirror-design.md)
- [Fork Outdated Notifier](docs/fork-outdated-notifier.md)

## Mirror Infisical

工作流文件在 `.github/workflows/mirror-infisical.yml`。

它每天自动运行一次，也可以在 GitHub Actions 页面手动触发。运行时把 `github.com/infisical/infisical` 的 `main` 分支和全部 tags 原样（SHA 保真）同步到目标私有仓库：目标分支缺失时用全量克隆做一次性 seed，之后每轮用 blobless 克隆目标仓库作为对象缓存，只从上游拉取增量并快进推送。`main` 使用绑定旧 SHA 的 `--force-with-lease` 更新，tags 跟随上游强制更新。上游重写历史时镜像会跟随，不归档旧 tip。

目标仓库上可以维护一个 `custom` 分支存放自己的提交。每次镜像完成后，工作流会把它 rebase 到新的 `main` 顶端并推送；已经位于顶端的 custom 分支会被跳过，不会反复重写。rebase 冲突或上游历史重写导致无法自动 rebase 时，`main` 和 tags 照常镜像，custom 保持原样，job 以失败结束并给出提示，等人工处理。

### 需要配置的 secrets

`FNOX_AGE_KEY` 是解密 `fnox.toml` 的 age 私钥（`AGE-SECRET-KEY-...` 字符串）。

目标仓库的凭据不放在 GitHub secrets 里，而是加密提交在仓库根目录的 `fnox.toml` 中，由 `fnox exec` 在运行任务时解密并注入环境变量：

```bash
fnox set INFISICAL_MIRROR_URL https://github.com/example/infisical.git
fnox set INFISICAL_MIRROR_USERNAME example
fnox set INFISICAL_MIRROR_TOKEN ghp_xxx
```

`INFISICAL_MIRROR_URL` 是目标私有仓库的 HTTPS 地址；`INFISICAL_MIRROR_USERNAME` 是目标远端的 HTTPS 用户名；`INFISICAL_MIRROR_TOKEN` 是目标远端的 HTTPS token（GitHub PAT）。

### 需要配置的变量

`INFISICAL_MIRROR_BRANCH` 可以放在 repository variables 里，值是要推送到的目标分支名，不配置时使用 `main`。

`CUSTOM_BRANCH` 可以放在 repository variables 里，值是要 rebase 到 main 顶端的自定义分支名，不配置时使用 `custom`。目标仓库上没有这个分支时本轮跳过，不影响镜像。

`GIT_USER_NAME` 可以放在 repository variables 里，值是 Git 提交身份里的用户名，不配置时使用 `github-actions[bot]`。

`GIT_USER_EMAIL` 可以放在 repository variables 里，值是 Git 提交身份里的邮箱，不配置时使用 `41898282+github-actions[bot]@users.noreply.github.com`。

### 推送行为

目标分支只在首次 seed 或上游非 fast-forward 更新时使用受 lease 保护的强制推送，正常同步都是快进。上游移动的 tag 会跟随；上游删除的 tag 不会从目标删除。

custom 分支由工作流独占维护：只在需要 rebase 时用绑定旧 SHA 的 lease 强制推送，其余情况不触碰。上游重写历史导致 custom 与 main 不再共享历史时，工作流失败告警并保留 custom，等待人工处理。

### 本地开发

自己的提交不需要在本地维护完整仓库。维护 custom 分支时，本地可以用 blobless + sparse 的最小克隆：

```bash
git clone --filter=blob:none --sparse --single-branch --branch custom https://github.com/<you>/<target>.git
git sparse-checkout set <你要改动的目录>
```

工作流在服务端完成 rebase 后，本地 `git pull --rebase` 即可（本地没有未推送提交时也可以 `git fetch && git reset --hard origin/custom`）。

### 备份

目标私有仓库可以用 Forgejo 的 pull mirror 指向它做整体备份；pull mirror 会把 main、tags 和 custom 一起镜像。

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
