# Forgejo 默认分支镜像与历史归档设计

## 状态

- 阶段：待实现
- 目标仓库：`YewFence/actions`
- 执行器：GitHub Actions
- 目标服务：Forgejo HTTPS Git 远端
- 同步范围：上游当前默认分支

## 背景

Forgejo pull mirror 面向上游当前状态，不保证保留被 force-push 或删除后失去引用的旧提交；上游仓库不可访问时，已有镜像通常仍会保留，但上游成功发布重写后的历史时，镜像也会跟随重写。这个仓库因此使用独立的定时工作流：在覆盖目标分支前比较新旧提交，并为历史重写或默认分支变更创建不可变归档引用。首版只处理默认分支，不同步 tags 和其他 branches。

## 目标

- 使用一份 TOML 清单集中声明需要备份的公开 HTTPS Git 仓库。
- 自动发现每个上游仓库当前的默认分支，不假设它名为 `main` 或 `master`。
- 将上游默认分支同步到指定 Forgejo 用户名下的同名仓库。
- 目标仓库不存在时使用 Forgejo CLI `fj` 创建私有仓库。
- 上游默认分支发生非 fast-forward 更新时，先归档旧提交，再更新当前分支。
- 上游更换默认分支时，归档并移除旧默认分支，推送新默认分支，并同步修改目标仓库的默认分支设置。
- 每 6 小时运行一次，同时支持手动同步全部仓库或单个仓库。
- Forgejo token 只来自 GitHub Actions Secret，不写入清单、Git remote URL 或日志。

## 非目标

- 不同步或归档非默认分支和 tags。
- 不备份 Issues、Pull Requests、评论、Wiki、Releases、Actions artifacts 或其他 Forgejo 元数据。
- 不备份 Git LFS 对象。
- 不支持需要认证的上游仓库。
- 不保证找回两次成功运行之间已经出现并再次消失、从未被任务观察到的提交。
- 不保护目标仓库已有内容；同名仓库存在时，工作流会按本设计直接同步并可能覆盖其当前默认分支。
- 不把 Forgejo 配置成平台内置的 pull mirror；同步和归档均由本仓库的 GitHub Actions 工作流负责。

## 核心决策

### 只跟踪上游默认分支

工作流使用 Git 协议提供的远端 `HEAD` 符号引用发现默认分支：

```bash
git ls-remote --symref "$SOURCE_URL" HEAD
```

正常的 Git smart HTTP 服务会返回类似结果：

```text
ref: refs/heads/main	HEAD
<commit-sha>	HEAD
```

这个机制属于 Git 协议，不依赖 GitHub API，在 GitHub、Forgejo、GitLab、Codeberg 和正常配置的 `git-upload-pack` 服务上均可使用。工作流必须同时获得合法的 `refs/heads/...` 符号引用和对应 commit SHA；如果上游使用不支持符号引用的旧式 HTTP 服务、`HEAD` 配置错误、仓库为空，或命令执行失败，本轮同步失败且目标仓库保持不变。工作流不得猜测 `main` 或 `master`。

首版只观察解析出的默认分支。其他 branches 和 tags 即使被创建、改写或删除，也不参与同步和归档。

### 当前分支与归档分支分离

目标仓库中的普通默认分支表示上游当前状态，允许 fast-forward 或受控的强制更新。被替换的旧状态使用只增不改的归档分支保存：

```text
refs/heads/main
    上游当前默认分支。

refs/heads/archive/heads/main/2026-08-15T12-30-00Z-<old-sha>
    main 被非 fast-forward 更新前的旧 tip。

refs/heads/archive/heads/master/2026-08-15T12-30-00Z-<old-sha>
    上游从 master 更换默认分支前的旧 tip。
```

归档分支指向旧 tip，即可保留从该提交可达的完整提交图。名称使用 UTC 时间和完整旧 SHA，创建后不得覆盖、复用或由正常同步删除。

### 允许直接接管同名目标仓库

目标仓库名默认取上游 URL 路径最后一段并移除 `.git` 后缀，也可以通过清单中的 `name` 显式覆盖。同一个目标用户名下的目标名必须唯一。

如果目标仓库已经存在，工作流不会验证它是否由本编排器创建，也不会要求管理标记，而是直接把它纳入同步。目标分支可能被强制更新，旧目标默认分支可能因上游更换默认分支而被归档和删除，因此维护者必须确保清单中的目标名称没有指向需要保留的其他仓库。

## 仓库结构

计划新增以下文件：

```text
.
├── mirrors.toml
├── scripts/
│   └── render-mirror-matrix.py
├── tests/
│   └── test_render_mirror_matrix.py
└── .github/
    └── workflows/
        └── mirror-repositories.yml
```

`mirrors.toml` 是维护者使用的唯一配置接口。渲染器使用 Python 标准库 `tomllib` 完成解析和校验，并输出 GitHub Actions 动态 matrix；Python 命令继续由仓库既有的 `uv` 运行。

## 配置模型

```toml
[[mirrors]]
repository = "https://github.com/owner/example.git"

[[mirrors]]
repository = "https://codeberg.org/another/project.git"
name = "project-backup"
```

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `repository` | 是 | 无需认证即可访问的 HTTPS Git 仓库 URL |
| `name` | 否 | 目标 Forgejo 仓库名；默认取 `repository` 的仓库 basename |

配置校验规则：

- `repository` 必须使用 `https`，必须包含主机名和至少一段仓库路径。
- URL 不允许包含用户名、密码、查询参数或 fragment。
- 仓库 basename 移除可选的 `.git` 后缀后必须非空。
- `name` 必须满足 Forgejo 仓库名称约束，且不能包含 `/`。
- 解析出的目标仓库名必须唯一，防止两个同名上游默认写入同一个目标仓库。
- 未知字段视为错误，避免拼写错误被静默忽略。
- 清单不得声明 branch；默认分支始终从本轮上游 `HEAD` 解析。

渲染器输出 GitHub Actions 可直接传给 `fromJSON` 的紧凑 JSON：

```json
{"include":[{"name":"example","repository":"https://github.com/owner/example.git"}]}
```

手动触发的 `name` 输入只能筛选已通过校验的清单项，不能替换来源 URL 或目标名称。

## Forgejo 配置与认证

工作流读取以下 GitHub Actions 配置：

| 名称 | 来源 | 含义 |
| --- | --- | --- |
| `FORGEJO_HOST` | Variable 优先，Secret 兜底 | Forgejo 实例的 HTTPS 根 URL |
| `FORGEJO_USERNAME` | Variable 优先，Secret 兜底 | 目标仓库所属用户名，也是 HTTPS Git 认证用户名 |
| `FORGEJO_TOKEN` | Secret | `fj` API 调用和 Git HTTPS 推送使用的 token |

对应的工作流环境变量形态为：

```yaml
env:
  FORGEJO_HOST: ${{ vars.FORGEJO_HOST || secrets.FORGEJO_HOST }}
  FORGEJO_USERNAME: ${{ vars.FORGEJO_USERNAME || secrets.FORGEJO_USERNAME }}
  FORGEJO_TOKEN: ${{ secrets.FORGEJO_TOKEN }}
```

`FORGEJO_TOKEN` 所属账户必须与 `FORGEJO_USERNAME` 相同，并至少拥有读取、创建和修改该账户仓库以及推送 Git refs 的权限。`FORGEJO_HOST` 必须是包含 `https://`、不带路径和末尾 `/` 的实例根 URL；目标 remote 由经过校验的配置构造成：

```text
<FORGEJO_HOST>/<FORGEJO_USERNAME>/<name>.git
```

URL 中不得包含 token。Git 认证通过临时 `GIT_ASKPASS` 程序提供用户名和 token，程序及其环境只存在于需要推送的 job 中；不得使用会把凭据持久化到 runner 磁盘的 `credential.helper store`，也不得启用可能输出认证信息的 shell tracing。

## 目标仓库生命周期

### 查询与创建

每个 matrix job 使用 `fj repo view` 查询 `${FORGEJO_USERNAME}/${name}`。查询失败时执行：

```bash
fj repo create "$name" --private --yes
```

`fj` 自动读取 `FORGEJO_HOST` 和 `FORGEJO_TOKEN`。创建成功后继续同步；创建失败时再次查询，以处理另一个任务刚好创建了同名仓库的竞争。第二次查询仍失败时，任务同时输出首次查询错误和创建错误并停止，不继续推送。这个流程不解析 `fj` 面向用户的错误文本，也不绕过 CLI 发出容易被 Cloudflare 单独拦截的裸 HTTP 请求。`fj` 由仓库现有的 `mise.toml` 管理，工作流安装时显式设置 `MISE_OFFLINE=0`。

### 修改默认分支

`fj` 已提供设置目标仓库默认分支的命令：

```bash
fj repo edit \
  --repo "${FORGEJO_USERNAME}/${name}" \
  --default-branch "$branch" \
  --yes
```

新分支必须先成功推送，才能把目标仓库默认分支切换过去。切换成功后才能删除旧默认分支，避免 Forgejo 拒绝删除当前默认分支，也避免目标仓库短暂指向不存在的默认分支。

## 单仓库同步算法

### 读取状态

工作流对来源和目标分别执行 `git ls-remote --symref <remote> HEAD`，并严格区分命令失败与合法输出：

1. 来源命令必须成功，并解析出 `source_branch` 和 `new_sha`。
2. 新建的空目标仓库没有现有默认分支，进入首次推送流程。
3. 非空目标仓库解析出 `target_branch` 和 `old_sha`；目标 `HEAD` 无法解析时任务失败，不猜测目标分支。
4. 将来源的新提交和目标的旧提交抓取到本地临时 bare repository，以便比较提交关系和推送归档。

来源访问失败、认证失败、TLS 失败、无有效 `HEAD` 或输出无法解析时，不创建归档、不删除引用、不更新目标。

### 状态处理

| 状态 | 处理 |
| --- | --- |
| 目标仓库为空 | 推送来源默认分支，再将其设为目标默认分支 |
| 分支名相同，SHA 相同 | 不推送 |
| 分支名相同，`new_sha` 是 `old_sha` 的后代 | 使用 fast-forward 推送更新目标分支 |
| 分支名相同，`new_sha` 不是 `old_sha` 的后代 | 先归档 `old_sha`，再使用带 lease 的强制推送更新目标分支 |
| 来源默认分支名与目标默认分支名不同 | 归档旧目标分支，推送新分支，修改目标默认分支，然后删除旧普通分支 |
| 无法确认来源状态 | 不修改目标，任务失败 |

祖先关系使用 Git 自身判断：

```bash
git merge-base --is-ancestor "$old_sha" "$new_sha"
```

普通更新使用 fast-forward push。非 fast-forward 更新必须使用绑定已读取旧 SHA 的 lease：

```bash
git push target \
  "$new_sha:refs/heads/$source_branch" \
  --force-with-lease="refs/heads/$source_branch:$old_sha"
```

不能使用无条件 `--force`，也不能使用 `git push --mirror`；后者会越过首版范围，修改 tags、其他 branches 和归档 refs。

### 历史归档

发生非 fast-forward 更新或上游默认分支变更时，先创建归档分支：

```text
refs/heads/archive/heads/<old-branch>/<UTC-time>-<old-sha>
```

归档 push 必须是普通创建，不带 `--force`。如果同名归档已经存在、推送被拒绝或发生其他错误，本轮任务立即失败，不得继续覆盖或删除当前分支。

成功创建归档后，即使后续当前分支更新失败，也保留已经创建的归档。下一轮运行会重新读取目标状态；归档名称包含完整旧 SHA，因此可以审计和去重。

### 默认分支变更的安全顺序

当上游 `HEAD` 从例如 `master` 改为 `main` 时，按以下顺序执行：

1. 读取并固定目标 `master` 的旧 SHA。
2. 创建指向旧 SHA 的 `archive/heads/master/...`。
3. 推送来源 `main` 到目标 `refs/heads/main`；若目标已有同名分支，则使用基于其实际旧 SHA 的更新规则，不能盲目覆盖。
4. 使用 `fj repo edit --default-branch main` 修改目标仓库默认分支。
5. 使用绑定旧 SHA 的 lease 删除目标普通 `master`。

任一步骤失败都让 job 失败。归档失败时后续步骤不执行；新分支推送成功但修改默认分支失败时保留新分支和旧默认分支；修改默认分支成功但删除旧分支失败时保留两个普通分支，并在下一轮重试清理。

如果上游 `HEAD` 不再解析到任何 branch，工作流无法安全地区分空仓库、错误配置和被删除的默认分支，因此保留目标现状并失败告警。只有成功解析到新的默认分支时，才把旧默认分支视为已被替换并执行归档和删除。

## GitHub Actions 工作流

### 触发器与并发

```yaml
on:
  schedule:
    - cron: "17 */6 * * *"
  workflow_dispatch:
    inputs:
      name:
        description: Mirror name (leave empty to sync all mirrors)
        required: false
        type: string

concurrency:
  group: mirror-repositories
  cancel-in-progress: false
```

定时任务每 6 小时在非整点运行。GitHub Actions 的 schedule 可能延迟或跳过排队任务，因此工作流同时保留手动触发；这个频率只缩短观察窗口，不构成连续备份保证。

清单、渲染器或工作流在默认分支发生变更时也执行同步。Pull Request 只运行配置解析器及其测试，不向含有 Forgejo 凭据的同步 job 传递数据，也不访问或修改目标服务。

全局 concurrency 禁止两个 workflow run 同时修改目标；matrix 中不同目标仓库可以有限并行，初始 `max-parallel` 使用 `4`。即使已有全局并发控制，每次引用更新仍必须使用 lease，防止人工操作或其他客户端在任务运行期间被覆盖。

### Job 划分

`check` job：

1. checkout 当前编排仓库。
2. 使用 `uv run python` 执行渲染器测试。
3. 解析和完整校验 `mirrors.toml`。
4. 按手动输入筛选清单项并输出 matrix。
5. 在 job summary 中列出来源 URL 和目标仓库名。

`mirror` matrix job：

1. 校验 `FORGEJO_HOST`、`FORGEJO_USERNAME` 和 `FORGEJO_TOKEN` 均非空。
2. 通过 mise 提供 `fj`，输出版本但不输出 token 或详细 API trace。
3. 解析上游默认分支和 commit。
4. 查询或创建目标私有仓库。
5. 读取目标默认分支和 commit。
6. 按同步算法抓取、比较、归档和更新。
7. 在 job summary 中记录来源、目标、默认分支、旧 SHA、新 SHA、归档引用和最终操作。

`strategy.fail-fast` 设为 `false`，一个仓库失败不会取消其他仓库，但任意 matrix job 失败都会让整轮 workflow 显示失败。

## 安全模型

- 只有默认分支中的清单、渲染器和工作流被视为可信发布配置。
- Pull Request 不能进入带 Forgejo secrets 的 job。
- 上游仓库内容不受信任；任务只执行 Git 对象传输和引用比较，不 checkout 或执行上游脚本、hooks、Actions 或构建文件。
- 上游 URL 只允许 HTTPS 且不包含 userinfo，防止把清单变成明文凭据载体。
- `FORGEJO_TOKEN` 不得作为命令行参数、URL、Git config 值、artifact、cache 或 job summary 的一部分。
- 不启用 `fj --verbose`、`set -x` 或其他可能输出认证请求细节的调试模式。
- 所有目标 ref 名都来自经过校验的默认分支和目标名称；在拼接 refspec 前仍使用 `git check-ref-format` 验证完整 ref。
- 目标仓库默认创建为 private，工作流不自动修改已有仓库的可见性。
- 因为设计允许直接接管已有同名仓库，添加或修改清单项必须经过维护者审查；这是本方案明确接受的覆盖风险。

## 失败语义与可观测性

- 上游或目标的引用发现失败时不修改目标仓库。
- 归档失败时不更新当前默认分支。
- 非 fast-forward 更新和默认分支变更都会在 summary 中突出显示，并将完整变化结果写入 `GITHUB_OUTPUT`；即使归档和同步成功，job 也以失败状态结束，从而以 GitHub Actions 失败通知作为唯一告警渠道。
- 普通 fast-forward、首次创建和无变化同步正常成功。
- 日志至少包含目标仓库名、变化类型、分支名和缩短后的 SHA；summary 可以记录完整 SHA 和归档引用，但不能包含认证 URL。
- 工作流不主动重试有写入副作用的步骤；失败后由下一次定时任务或人工 `workflow_dispatch` 重新读取实际远端状态并恢复。

## 测试与验收

### 配置渲染器

使用标准库 `unittest` 覆盖：

- 合法的最小配置、自定义 `name` 和多个仓库。
- 从有无 `.git` 后缀的 URL 推导默认名称。
- 手动选择单个已声明目标。
- 非 HTTPS URL、userinfo、query、fragment 和空路径。
- 非法或重复的显式名称，以及两个 URL 解析成同一默认名称。
- 未知字段、空清单和不存在的手动选择。

### Git 同步逻辑

使用本地 bare repositories 测试，不依赖外部网络或真实 Forgejo token：

- 首次同步创建当前默认分支。
- 默认分支 fast-forward 时不创建归档。
- 默认分支 force-push 时先创建唯一归档，再更新当前分支。
- lease 不匹配时拒绝覆盖并保留目标实际状态。
- 上游从 `master` 切换到 `main` 时归档旧分支、更新默认分支操作计划并删除旧普通分支。
- 上游 `HEAD` 缺失、无效或命令失败时不产生任何目标 ref 更新。
- tags 和其他 branches 不被抓取、推送、归档或删除。
- 已有目标同名分支进入相同的比较和 lease 规则，而不是无条件覆盖。

### `fj` 集成边界

本地开发环境没有可用于创建目标仓库的 Forgejo token，因此当前只依据帮助信息确认以下接口：

- `fj repo create <REPO> --private --yes`
- `fj --json repo view <OWNER/REPO>`
- `fj repo edit --repo <OWNER/REPO> --default-branch <BRANCH> --yes`
- `FORGEJO_HOST` 和 `FORGEJO_TOKEN` 环境变量

上线前必须在一次手动触发中使用专用测试仓库验证：不存在仓库的查询与创建、HTTPS Git 认证、默认分支修改以及已有仓库查询。验证不能在 Pull Request 工作流中运行。

## 实施顺序

1. 实现 `mirrors.toml`、配置渲染器和单元测试。
2. 实现可对本地 bare repositories 运行的默认分支解析、比较和归档脚本，并覆盖同步状态测试。
3. 实现只支持 `workflow_dispatch` 单仓库选择的工作流，使用专用 Forgejo 测试仓库验证 `fj` 和 HTTPS 推送。
4. 增加多仓库 matrix、默认分支切换和失败 summary。
5. 启用配置变更触发和每 6 小时的 schedule。
6. 在出现实际需求后，再单独设计 tags 和其他 branches 的同步及归档语义。
