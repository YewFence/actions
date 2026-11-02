# GitHub Actions Collection

这里放一些我自己会用到的 GitHub Actions 工作流。

这个仓库后续可能会继续加入别的零散自动化任务，所以每个工作流都会尽量独立配置，避免互相影响。

每个工作流一份设计文档，按工作流文件名放在 [docs/](docs/)：设计背景、配置项、运维细节都在对应文档里。

| 工作流 | 文档 | 一句话 |
| --- | --- | --- |
| `build-binaries.yml` | [预编译二进制发布](docs/build-binaries.md) | 按上游源码 commit 锁定构建并发布带 packslip 签名的 Linux 预编译工具，首批是 Josh |
| `build-images.yml` | [声明式容器镜像编排器](docs/build-images.md) | 用 Docker Bake 声明镜像，从上游 Git context 多平台原生构建并发布到 GHCR |
| `clean-build-image-runs.yml` | — | 镜像构建完成后删除对应的 workflow run，保持 Actions 列表干净（属 build-images 的附属清理，无独立设计） |
| `mirror-infisical.yml` | [Infisical 镜像](docs/mirror-infisical.md) | SHA 保真镜像 Infisical 的 main 和 tags 到私有仓库，并把 custom 分支自动 rebase 到新 main |
| `mirror-repositories.yml` | [Forgejo 默认分支镜像与历史归档](docs/mirror-repositories.md) | 按 `mirrors.toml` 清单把公开仓库默认分支镜像到 Forgejo，历史重写前先归档 |
| `fork-outdated-notifier.yml` | [Fork Outdated Notifier](docs/fork-outdated-notifier.md) | 每天检查名下 fork 是否落后上游，汇总成一条 Telegram 消息 |

安装仓库发布的预编译工具（以 josh 为例）：

```bash
mise use -g packslip:github.com/YewFence/actions/josh
```

本地开发：`mise run check` 跑 lint 和测试。
