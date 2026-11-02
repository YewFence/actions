# Infisical 镜像

## 状态

- 阶段：已实现
- 目标仓库：`YewFence/actions`
- 执行器：GitHub Actions
- 上游：`github.com/infisical/infisical`（main + 全部 tags）
- 目标：私有仓库（Forgejo，由 `fnox.toml` 加密持有凭据）

## 背景

Infisical 上游只维护一支演进中的 main，历史提交可能被 force-push 重写。这个工作流把上游 main 和全部 tags 以 SHA 保真的方式镜像到一个私有目标仓库，并维护一支 `custom` 分支承载自己的提交：每轮镜像后自动把它 rebase 到新的 main 顶端。

## 目标

- `main` 与全部 tags 原样同步（SHA 保真），目标分支缺失时用全量克隆做一次性 seed。
- 日常轮次使用 blobless 克隆目标仓库作为对象缓存，只从上游拉增量并快进推送。
- `main` 使用绑定旧 SHA 的 `--force-with-lease` 更新；tags 跟随上游强制更新，不归档旧 tip。
- `custom` 分支由工作流独占维护：仅在需要时用绑定旧 SHA 的 lease 强制推送 rebase 结果。
- 凭据不进 GitHub secrets，由仓库内加密的 `fnox.toml` 在运行时解密注入。

## 非目标

- 不归档被上游 force-push 覆盖的旧历史（如需归档语义见 [mirror-repositories.md](mirror-repositories.md)）。
- 不镜像 main 和 tags 之外的 ref。

## 配置

### Secrets

`FNOX_AGE_KEY` 是解密 `fnox.toml` 的 age 私钥（`AGE-SECRET-KEY-...` 字符串）。

目标仓库的凭据不放在 GitHub secrets 里，而是加密提交在仓库根目录的 `fnox.toml` 中，由 `fnox exec` 在运行任务时解密并注入环境变量：

```bash
fnox set INFISICAL_MIRROR_URL https://github.com/example/infisical.git
fnox set INFISICAL_MIRROR_USERNAME example
fnox set INFISICAL_MIRROR_TOKEN ghp_xxx
```

- `INFISICAL_MIRROR_URL`：目标私有仓库的 HTTPS 地址。
- `INFISICAL_MIRROR_USERNAME`：目标远端的 HTTPS 用户名。
- `INFISICAL_MIRROR_TOKEN`：目标远端的 HTTPS token。

### Variables

- `INFISICAL_MIRROR_BRANCH`：要推送到的目标分支名，缺省 `main`。
- `CUSTOM_BRANCH`：要 rebase 到 main 顶端的自定义分支名，缺省 `custom`；目标上没有该分支时本轮跳过。
- `GIT_USER_NAME` / `GIT_USER_EMAIL`：提交身份，缺省 `github-actions[bot]` 及其 noreply 邮箱。

## 运行行为

每天自动运行一次，也可手动触发。

推送语义：目标分支只在首次 seed 或上游非 fast-forward 更新时使用受 lease 保护的强制推送，正常同步都是快进。上游移动的 tag 会跟随；上游删除的 tag 不会从目标删除。

custom 分支：每轮镜像完成后 rebase 到新的 main 顶端并推送；已经位于顶端的 custom 分支会被跳过，不会反复重写。rebase 冲突或上游历史重写导致无法自动 rebase 时，`main` 和 tags 照常镜像，custom 保持原样，job 以失败结束并给出提示，等人工处理。

## 本地开发

自己的提交不需要在本地维护完整仓库。维护 custom 分支时，本地可以用 blobless + sparse 的最小克隆：

```bash
git clone --filter=blob:none --sparse --single-branch --branch custom https://github.com/<you>/<target>.git
git sparse-checkout set <你要改动的目录>
```

工作流在服务端完成 rebase 后，本地 `git pull --rebase` 即可（本地没有未推送提交时也可以 `git fetch && git reset --hard origin/custom`）。

## 备份

目标私有仓库可以用 Forgejo 的 pull mirror 指向它做整体备份；pull mirror 会把 main、tags 和 custom 一起镜像。
