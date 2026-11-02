# 预编译二进制发布

## 状态

- 阶段：已实现
- 目标仓库：`YewFence/actions`
- 执行器：GitHub Actions
- 发布渠道：GitHub Releases + packslip 签名

## 背景

一些工具不提供官方 Linux 预编译产物（或只覆盖部分平台），但可以通过源码构建。本工作流用容器按上游源码 commit 锁定构建，把产物以 GitHub Release 形式发布，并通过 packslip 签名，让 mise 可以校验安装。

## 方案调研结论

Josh 上游只发布 Docker 镜像，不提供二进制产物；从镜像里抽取二进制不是受支持的用法，因此本仓库自行从源码构建。

## 配置模型

工具声明在仓库根目录的 [binaries.toml](../binaries.toml)。每个工具锁定：

- `source`：上游仓库 HTTPS URL。
- `tag` 与 `revision`：上游 release tag 及其完整 commit SHA，两者由 Renovate 的 `custom.regex` manager 一起自动升级。
- `version_pattern`：从 tag 提取语义化版本的正则（如 Josh 的 `r26.08.28` → `26.8.28`）。
- `commands`：构建产物的命令列表。
- `notes`：Release notes 模板，支持 `{source_tag}`、`{revision}`、`{commands}` 占位符。
- `platforms`：平台矩阵，每项声明 `platform`（平台标签）、`target`（Rust 风格 triple，作矩阵键）、`runner`（GitHub-hosted runner 标签）。

首个（目前也是唯一的）工具是 `josh`，提供 Linux amd64 和 arm64 的 `josh`、`josh-filter`。

## 工作流结构

`.github/workflows/build-binaries.yml` 分四个 job：

1. `prepare`：运行 `mise run check`，然后用 `binaries:prepare` 生成固定版本的发布计划（release.json + notes.md），以 artifact 传递。
2. `build`（matrix）：按平台在对应原生 runner 上用 BuildKit 容器构建打包，产物为 `*.tar.gz` artifact。
3. `sign`：仅在默认分支 push 或手动选择发布时运行，用 packslip 对产物签名并生成签名 bundle。
4. `publish`：创建 GitHub Release（先 draft 再发布，`--latest=false`），上传 tar.gz 与签名 bundle。

构建配方（Dockerfile 等）存放在 `binaries/<tool>/` 下，配方自身的演进历史锁定在发布时的工作流 commit 上，Release notes 会记录该 commit。

## 使用

安装（以 josh 为例）：

```bash
mise use -g packslip:github.com/YewFence/actions/josh
```

Josh 需要 Git 命令在 `PATH` 中；`josh changes pull` 要求 Git 2.41 或更高版本。Linux GNU 构建需要 glibc 2.36 或更高。

## 触发

- `binaries.toml`、`binaries/**`、构建脚本或工作流在 main 变更时自动发布。
- 手动触发时可选择工具，并可选是否发布（默认只构建不发布）。
- Pull request 只构建不发布，不接触签名与发布凭据。
