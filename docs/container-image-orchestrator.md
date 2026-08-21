# 声明式容器镜像编排器设计

## 状态

- 阶段：已实现
- 目标仓库：`YewFence/actions`
- 目标注册表：GitHub Container Registry（GHCR）
- 发布命名空间：`ghcr.io/yewfence`

## 背景

本设计在当前仓库中建立一个集中式编排层。镜像清单声明公开或私有的 GitHub 上游仓库及其构建参数，单个定时工作流读取清单、生成构建矩阵，并将构建结果统一发布到公开的 GHCR 命名空间。

## 目标

- 通过修改一份声明式清单来增加、修改或停用镜像，不为每个镜像复制工作流。
- 从公开或私有的 GitHub 仓库构建镜像，并发布为 `ghcr.io/yewfence/<name>:latest`。
- 支持定时构建、手动构建和配置变更后的构建。
- 支持单架构和常见的多架构镜像。
- 将每个镜像放在独立 job 中构建，使失败和日志彼此隔离。
- 使用仓库自带的 `GITHUB_TOKEN` 和最小权限发布，不引入 PAT 或其他长期凭据。
- 保留实际构建的上游 commit 和镜像 digest，方便定位 `latest` 的来源。

## 非目标

- 不监听上游仓库事件；上游更新通过下一次定时构建被拉取。
- 不发现或同步上游 release、Git tag 和语义化版本。
- 不发布除 `latest` 之外的版本标签。
- 不自动修改 GHCR package 的可见性或权限。
- 不自动清理旧 manifest、无标签镜像或 Actions cache。
- 不接受任意用户提交的仓库 URL、Dockerfile 路径或构建参数。
- 不自动判断第三方项目的许可证是否允许重新分发。

## 核心决策

### 集中编排，不以 fork 作为构建载体

所有来源都由当前仓库的一个工作流构建。只有当镜像必须长期携带源码补丁、维护自有 Dockerfile，或需要独立 Secrets 和发布节奏时，才为该项目建立 fork。即使以后出现这种情况，也应优先让 fork 调用可复用工作流，避免复制构建实现。

集中编排带来的主要取舍是不能直接收到上游 `push` 事件。本项目不追求即时发布，因此定时拉取符合需求。

### `images.toml` 是唯一配置接口

镜像维护者只需要理解 `images.toml`。TOML 解析、校验、矩阵 JSON、GitHub Actions 表达式、Buildx 参数和 GHCR 登录都属于编排器的实现，不暴露为每个镜像都要维护的配置。公开仓库中的 `images.toml` 保存非敏感镜像声明；需要私有源凭据时，通过 Infisical OIDC action 将同格式 TOML 放入 `IMAGES_TOML` 环境变量，工作流在 runner 内合并两者。

首版接口保持克制：只有出现真实构建需求时才增加 build args、Buildx target、构建 secret 或自定义标签等字段。删除编排器后，这些逻辑会重新散落到每个镜像的工作流中，因此集中模块能够提供实际的复用价值和维护局部性。

### 始终重建，不做上游变更检测

定时任务每次重新构建所有启用的镜像。即使上游 commit 没变，重建也可以吸收基础镜像更新。首版不调用 GitHub API 比较 commit，也不查询 GHCR 标签或维护外部状态。

### `latest` 是最近一次成功构建

`latest` 不代表上游 release，也不承诺可复现。每次成功构建用新 manifest 更新该标签；失败时保留此前成功发布的 `latest`。工作流记录解析后的上游 commit 和发布 digest，以便追溯具体内容。

## 仓库结构

```text
.
├── images.toml
├── mise.toml
├── scripts/
│   ├── render-image-matrix.py
│   └── render-workflow-summary.py
├── tests/
│   ├── test_render_image_matrix.py
│   └── test_render_workflow_summary.py
└── .github/
    └── workflows/
        └── build-images.yml
```

`render-image-matrix.py` 使用 Python 标准库 `tomllib`，承担配置校验和矩阵生成；`render-workflow-summary.py` 将 matrix JSON 转换成 Markdown 构建计划。两者都通过 mise task 提供稳定入口，并由 `uv` 执行。

## 配置模型

```toml
[[images]]
name = "example"
repository = "owner/example"
ref = "main"
context = "."
dockerfile = "Dockerfile"
platforms = ["linux/amd64", "linux/arm64"]

[[images]]
name = "another"
repository = "owner/another"
ref = "main"
context = "docker"
dockerfile = "docker/Dockerfile"
platforms = ["linux/amd64"]

# 该段通常放在加密的 IMAGES_TOML 中，不要提交到仓库。
[[images]]
name = "private-example"
repository = "owner/private-example"
ref = "main"
username = "github-user"
password = "github-token"
```

字段语义：

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `name` | 是 | GHCR 中的 package 名，也是手动构建时的选择标识 |
| `repository` | 是 | 不含协议和主机名的 GitHub 仓库，格式为 `owner/repository`；公开或私有均可 |
| `ref` | 是 | 要构建的 branch、tag 或完整 commit SHA |
| `context` | 否 | 相对于上游仓库根目录的构建上下文，默认 `.` |
| `dockerfile` | 否 | 相对于上游仓库根目录的 Dockerfile，默认 `Dockerfile` |
| `platforms` | 否 | Buildx 目标平台，默认 `["linux/amd64"]` |
| `username` | 否 | 访问私有 GitHub 源码仓库的用户名；必须与 `password` 同时出现 |
| `password` | 否 | 访问私有 GitHub 源码仓库的密码或 token；必须与 `username` 同时出现 |

`IMAGES_TOML` 的内容必须是包含 `[[images]]` 表的 TOML。按 `name` 合并：同名项由环境变量中的字段覆盖仓库文件中的字段，环境变量中新增的镜像追加到列表。合并后仍执行全部校验。凭据不会写入 matrix JSON、job output、构建参数或 job summary；发布 job 只在 runner 内读取当前镜像的凭据，并将 `password` 作为 GitHub checkout token 使用。

Infisical OIDC action 使用 `continue-on-error: true`。如果 Infisical 不可用，工作流会继续使用公开的 `images.toml`，跳过本次未能合并的私有镜像，不让整轮公开镜像构建失败；这意味着私有镜像需要在下一次 Infisical 恢复后再发布。

首版校验规则：

- `name` 必须唯一、全小写，并符合 GHCR package 名允许的字符范围。
- `repository` 必须恰好是 `owner/repository`，不允许 URL、查询参数或本地路径。
- `ref` 必须非空。
- `context` 和 `dockerfile` 必须是仓库内的相对路径，不允许绝对路径或 `..` 路径段。
- `platforms` 不得为空，只允许编排器明确支持的平台。
- 未知字段视为错误，防止拼写错误被静默忽略。

渲染脚本输出 GitHub Actions 可以直接传给 `fromJSON` 的紧凑 JSON：

```json
{"include":[{"name":"example","repository":"owner/example","ref":"main","context":".","dockerfile":"Dockerfile","platforms":"linux/amd64,linux/arm64"}]}
```

## 工作流设计

### 触发器

工作流支持以下事件：

- `schedule`：每天在非整点时间运行，减少 GitHub Actions 高峰期延迟。
- `workflow_dispatch`：可选输入一个 `name`；空值构建全部镜像，非空值只能匹配清单中的镜像。
- `push`：默认分支上的清单、渲染脚本或工作流发生变化时构建。
- `pull_request`：校验配置和矩阵，真实构建第三方源码，但不登录 GHCR 或发布镜像。

同一时刻只运行一轮发布工作流。后续运行排队而不是取消正在发布的任务，避免两个 run 竞争更新同一个 `latest`。

### `check` job

`check` job 只需要 `contents: read`，负责：

1. checkout 当前编排仓库。
2. 通过 `mise run test` 执行仓库测试。
3. 通过 `image-render` task 解析并完整校验 `images.toml`。
4. 按手动输入筛选一个已声明的镜像，或者选择全部镜像。
5. 将标准化后的 matrix JSON 写入 job output。
6. 通过 `image-plan-summary` task 生成 Markdown，并由 workflow 写入 job summary。

matrix 校验和 Markdown 生成属于可移植逻辑，由 mise task 拥有；`GITHUB_OUTPUT` 与 `GITHUB_STEP_SUMMARY` 的写入仍由 workflow 负责。

### `smoke-build` matrix job

`smoke-build` job 只在 PR 中运行。动态 matrix 必须由前一个 job 生成，因此它依赖 `check`，并为每个 matrix 项：

1. checkout 指定的公开上游仓库和 `ref`，关闭凭据持久化。
2. 读取实际 checkout 的 commit SHA。
3. 设置 QEMU 和 Docker Buildx。
4. 使用配置声明的 context、Dockerfile 和全部目标平台执行真实构建。
5. 在 job summary 中记录镜像、上游 commit 和已验证的平台。

该 job 只有 `contents: read` 权限，不登录 GHCR，设置 `push: false`，也不读写发布 job 使用的 GitHub Actions cache。构建结果只存在于当前一次性 runner 的 BuildKit cache 中，job 结束后即丢弃。

### `publish` matrix job

`publish` job 不在 PR 中运行。它依赖 `check`，设置 `strategy.fail-fast: false`，每个 matrix 项执行：

1. checkout 指定的公开上游仓库和 `ref`，关闭凭据持久化。
2. 读取实际 checkout 的 commit SHA。
3. 设置 QEMU 和 Docker Buildx。
4. 使用 `GITHUB_TOKEN` 登录 `ghcr.io`。
5. 通过 Buildx 构建并推送 `ghcr.io/yewfence/<name>:latest`。
6. 写入上游仓库、上游 commit、构建时间等 OCI 标签。
7. 在 job summary 中记录镜像名称、上游 commit 和发布 digest。

发布 job 的基础权限为：

```yaml
permissions:
  contents: read
  packages: write
```

需要从 Infisical 读取 `IMAGES_TOML` 的 `check` 和 `publish` job 额外申请 `id-token: write`；PR 不执行 Infisical action。

固定版本的 Actions 通过仓库已有的 `pinact` 维护更新。首版不生成 artifact attestation，因此不申请 `attestations: write`。

### 缓存与并发

Buildx 使用 GitHub Actions cache，并以镜像名作为 cache scope，避免不同镜像覆盖彼此的缓存。matrix 设置有限的 `max-parallel`，初始值为 `4`，防止同时构建过多多架构镜像导致 GHCR 或上游下载短时拥塞。

缓存只影响性能，不参与正确性判断。缓存缺失、过期或被 GitHub 回收时，构建仍应从零开始成功完成。

## 安全模型

### 信任内容

- 默认分支中的 `images.toml`、渲染脚本和工作流是受信任的发布配置；Infisical 中的 `IMAGES_TOML` 是受保护的发布输入。
- 清单明确列出的仓库和 ref 被允许作为 Docker 构建输入。
- 固定到完整 SHA 的 GitHub Actions 被允许在 runner 上执行。

### 不信任内容

- PR 修改后的配置和脚本。
- 上游仓库的源码、Dockerfile 和构建期间下载的内容。
- `workflow_dispatch` 的输入值。

### 强制约束

- PR 事件绝不进入拥有 `packages: write` 的 job，也不执行 GHCR 登录步骤。
- PR 事件不读取 Infisical，因此不会把私有配置或凭据暴露给不受信任的 PR。
- PR 冒烟构建不配置 `type=gha` cache，无法写入或污染发布 job 使用的持久缓存。
- 手动输入只用于筛选已有 `name`，不能覆盖仓库、ref、路径、平台或目标镜像。
- 不把 `GITHUB_TOKEN`、源仓库密码、Docker 配置、Actions context 或其他凭据作为 build arg、BuildKit secret、文件或环境变量传入 Dockerfile。
- 不执行上游仓库中的脚本或 GitHub Actions；唯一允许的执行入口是 Docker/BuildKit 对 Dockerfile 的构建。
- 不从上游仓库读取工作流配置来改变发布目标或 job 权限。
- 每个构建使用 GitHub 托管的一次性 runner，镜像之间不共享工作目录。
- 为每个 matrix job 设置超时，避免异常构建长期占用 runner。

这些约束不能阻止已获准上游被攻陷后发布恶意 `latest`。这是自动跟随可变 ref 的固有供应链风险；本项目通过记录 resolved commit 和 digest 提供追溯能力，但首版不引入人工审批、签名白名单或 commit 固定策略。

## GHCR 行为

- 新镜像发布到 `ghcr.io/yewfence/<name>:latest`。
- 私有源只影响源码 checkout；构建结果仍发布到公开的 GHCR，公开构建记录和 digest 属于预期行为。
- 新 package 首次发布后，由维护者在 GHCR 设置中将其切换为 public。
- 如果同名 package 已存在，需要确保当前仓库拥有该 package 的 Actions 写权限。
- 镜像页面应明确说明它是自动构建的非官方镜像，并链接上游仓库和许可证。
- 删除或重命名清单项不会自动删除 GHCR 中已有的 package，是可以接受的取舍。

## 失败语义与可观测性

- 单个镜像失败不会取消其他 matrix job。
- 任意镜像失败都会让整轮 workflow 显示失败，便于发现部分镜像未更新。
- 构建失败不会主动删除或覆盖此前成功发布的 `latest`。
- 每个 job 的名称包含镜像 `name`，日志和 summary 包含上游仓库、ref、resolved commit 和目标镜像。
- GHCR 返回的 digest 是发布成功的最终依据；不能仅凭构建步骤退出码推断用户实际拉取到的内容。

## 测试与验证

### 配置渲染器

使用标准库 `unittest` 覆盖：

- 合法的最小配置和多镜像配置。
- 默认值填充和稳定的 JSON 输出。
- 按 `name` 筛选单个镜像。
- 重复名称、未知字段和空列表。
- 非法仓库格式、路径穿越、非法平台和不存在的手动选择。
- `IMAGES_TOML` 的同名覆盖、新增镜像、凭据成对校验，以及凭据不出现在 matrix JSON。

配置测试检查渲染器的公开接口：输入 TOML 与可选镜像名，输出 matrix JSON 或明确错误。不为 TOML 解析和 JSON 序列化建立额外 adapter。summary 测试使用代表性 matrix JSON 检查稳定的 Markdown 输出。

### 工作流

- PR 工作流验证 TOML、渲染脚本及其测试，并为全部声明平台执行真实构建，但不登录 GHCR、不使用发布 cache，也不执行发布 job。
- 首次上线先通过 `workflow_dispatch` 构建一个体积较小的测试镜像。
- 验证 GHCR package、`latest`、多架构 manifest、OCI 标签和 job summary 后再启用定时触发。
- 对关键 Actions 的 SHA 更新单独运行一次手动构建，确认行为未变化。

## 分阶段实施

1. 实现清单、渲染器、测试和只支持 `workflow_dispatch` 的单架构构建。
2. 用一个真实上游验证 GHCR 首次发布、公开可见性和无凭据构建。
3. 增加定时与配置变更触发，启用 cache、并发限制和多架构构建。
4. 根据真实镜像需求决定是否扩展 build args、Buildx target 或 artifact attestation；没有需求则保持现状。

## 未采用的方案

### 每个来源建立 fork 并维护工作流

该方案可以自然容纳源码补丁，但是每个仓库维护一份发布工作流也非常麻烦。

### 每个镜像一个独立工作流

这种方式容易起步，但登录、Buildx、缓存、权限和安全修复会复制到多个文件。镜像之间当前只有数据不同，因此差异应留在清单中，而不是复制实现。

### Docker Buildx Bake 作为外部配置接口

Bake 很适合复杂的本地构建图，但其 HCL/JSON/Compose 配置会把 Buildx 实现细节直接暴露给镜像维护者，并不能独立解决上游 checkout、PR 权限和手动筛选问题。首版使用 TOML 加小型渲染器，后续只有在真实构建图需要继承和组合时才重新评估 Bake。

### 自动检测上游变更后再构建

该方案能够减少重复构建，却需要查询并保存上游 commit 状态，还会跳过基础镜像更新。公开仓库标准 runner 当前免费，首版按日完整重建更简单，也更符合镜像刷新需求。

## 后续可能扩展

以下能力不预留配置字段，出现真实需求时再设计：

- 额外的不可变 commit 标签。
- artifact attestation 与 provenance。
- Buildx target、受控 build args 和 BuildKit secrets。
- 针对单个镜像的构建周期。
- 构建成功后的健康检查或容器 smoke test。
- GHCR 旧 manifest 清理。
- 需要补丁的 fork 通过可复用工作流接入。

## 参考资料

- [Publishing Docker images](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)
- [Choosing the runner for a job](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job)
- [Billing and usage](https://docs.github.com/en/actions/concepts/billing-and-usage)
- [Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use)
- [Docker build-push-action](https://github.com/docker/build-push-action)
