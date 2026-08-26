# Fork Outdated Notifier 设计

## 状态

- 阶段：已实现
- 目标仓库：`YewFence/actions`
- 执行器：GitHub Actions
- 通知渠道：Telegram Bot API

## 背景

需要定期知道自己名下的哪些 GitHub fork 落后于上游仓库，以免错过重要更新。GitHub 网页 UI 只在打开 fork 页面时才显示 behind 提示，没有主动通知机制。

## 方案调研结论

社区没有现成的“检查 fork 是否落后并通知”的 Action。已有的 fork 相关轮子都是**自动同步类**（fork-sync、upstream-sync 等，直接 merge/pull 上游改动），而不是**通知类**，且多数已不活跃维护。因此本仓库自行实现。

通知侧不发“能复用的轮子”，因为 Telegram Bot API 的 `sendMessage` 就是一个 HTTP POST（[core.telegram.org/bots/api#sendmessage](https://core.telegram.org/bots/api)），引入第三方 Action 反而多一个需要信任的供应链依赖。所有 GitHub/Telegram 请求均使用 Python 标准库 `urllib`，零第三方依赖。

## 检测原理

1. GraphQL `viewer.repositories(isFork: true)` 分页列出全部 fork，一次请求同时拿到 fork 默认分支和 `parent`（上游全名及其默认分支）。REST 的 `/users/{user}/repos` 对 fork 不返回 `parent` 字段，因此选 GraphQL。
2. 对每个 fork 调用 REST compare 端点：

   ```
   GET /repos/{parent}/compare/{parent_branch}...{fork_owner}:{fork_repo}:{fork_branch}
   ```

   base 为上游默认分支 head，head 为 fork 默认分支 head（`owner:repo:ref` 跨 fork 语法）。返回的 `behind_by > 0` 即判定 outdated；`ahead_by` 单独返回，天然满足“领先不算”。
3. 以上比较均围绕上游与 fork 各自的默认分支；不评估其他分支。

## 边界与失败处理

- 上游被删除/重命名/转为私有时，compare 返回 404：不判定为 outdated，仅在 Job Summary 中列出 “Upstream comparison unavailable”。
- fork 无默认分支（空仓库）或 parent 信息缺失时直接跳过。
- 归档（archived）fork 仍参与检查；不想要的放入忽略列表。
- Telegram 发送失败时输出 `::error::` 注解并以非零码退出（失败必须可见），但检查与 Summary 已经完成。
- 所有 outdated 条目合并为一条 Telegram 消息，避免消息轰炸。
- 权限：`FORKS_GH_TOKEN` 使用 PAT（经典或 fine-grained 均可），只需公开仓库的只读访问。工作流默认的 `GITHUB_TOKEN` 也能读公开仓库，可自行选择。注意 `GITHUB_TOKEN` 触发的工作流运行不会再触发其他工作流，对纯通知场景无影响。

## 配置

- `forks-ignore.txt`（仓库根目录）：忽略列表，每行一个仓库，支持 `owner/repo`（推荐）或裸仓库名（跨 owner 匹配），`#` 后内容视为注释。
- Secrets：`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`（可选；未配置时仅在 Summary 报告，不发消息）。
- Secret/Variable：`FORKS_GH_TOKEN`（可选；缺省回退到工作流自动注入的 `GITHUB_TOKEN`）。

## 频率建议

默认每天一次（`cron: "17 3 * * *"`，UTC）。GitHub 对定时工作流在负载高时会延迟甚至跳过运行，对通知场景可接受。

## 非目标

- 不自动同步 fork（同步类动作见社区 fork-sync 等方案，本工作流只做检测与通知）。
- 不检查私有仓库的上游状态。
- 不做增量状态记忆（上次已通知过的不再提醒）：每次运行只要仍落后就会再次通知，以此充当持续提醒。
