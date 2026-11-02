# 声明式容器镜像编排器设计

## 状态

- 阶段：已实现
- 目标仓库：`YewFence/actions`
- 目标注册表：GitHub Container Registry（GHCR）
- 发布命名空间：`ghcr.io/yewfence`

## 背景

本仓库使用 Docker Buildx Bake 作为镜像声明和构建入口。仓库内的 `docker-bake.hcl` 声明公开构建目标；加密的 `private-repo-bake.hcl.bin` 在受信任的发布 job 中解密为临时的 Bake HCL，用于增加私有 target。Docker Bake 直接使用上游 Git 仓库作为构建 context，不再由 Actions checkout 上游源码。

## 目标

- 通过一个 Bake 定义增加、修改或停用镜像，不为每个镜像复制工作流。
- 从公开或私有的 GitHub 仓库构建镜像，发布 `ghcr.io/yewfence/<target>:latest`，并在有明确上游版本时发布版本 tag。
- 支持手动构建、默认分支构建和 pull request smoke build。
- 在 `ubuntu-24.04` 与 `ubuntu-24.04-arm` 上分别原生构建 amd64 和 arm64。
- 让 Docker Bake 解析 target 和平台，不再维护镜像矩阵转换器。
- 使用 GitHub App installation token 访问需要权限的上游 Git context。
- 保留发布 digest，让 `latest` 与版本 tag 指向同一个多平台 manifest，并在 OCI 元数据中记录源码提交。

## 非目标

- 不监听上游仓库事件；上游更新通过下一次构建被拉取。
- 不自动选择最新 release 或改变 target 声明的分支；只识别实际构建提交上的版本 tag。
- 不发布 SHA tag，也不以版本 tag 代替不可变的镜像 digest。
- 不自动修改 GHCR package 的可见性或权限。
- 不自动判断第三方项目的许可证是否允许重新分发。

## 核心决策

### Docker Bake 是唯一构建配置

`docker-bake.hcl` 是公开构建配置的唯一事实来源。每个 target 的名称同时是 GHCR package 名和 workflow_dispatch 的选择值；target 内声明 Git context、Dockerfile、目标平台和 OCI labels。版本解析和发布计划生成由 `mise run images:prepare` 负责，计划中的 tag 最后由 `mise run images:manifest` 通过 `imagetools create` 统一发布；单平台构建仍按 digest 推送。

Bake 的多文件规则负责合并仓库配置和私有配置；私有 HCL 只声明新增 target，不重复公开 target。

### 版本与溯源

派生镜像通过 target 的 `dev.yewfence.image.version-source = "dockerfile"` label 声明版本来源。准备任务使用 Dockerfile parser 读取最终基础镜像的版本 tag，支持 Dockerfile 的 ARG 默认值与 Bake args 覆盖。版本只在 Dockerfile 维护，Renovate 更新基础镜像后无需再同步 HCL 中的版本。

未声明该 label 的 Git 源码目标，只在实际构建提交恰好对应 `vX.Y.Z` 或 `X.Y.Z`（可带预发布后缀）时增加版本 tag。带注解的 tag 使用解引用后的提交；分支领先 release 时仅发布 `latest`。多个不同版本指向同一提交时要求通过 context 显式选择 tag，避免猜测。

所有镜像写入 `org.opencontainers.image.revision`，值为实际构建 context 的完整源码 SHA。有明确版本时写入 `org.opencontainers.image.version`，否则置为空值以覆盖 Dockerfile 或基础镜像中可能遗留的版本；派生镜像另外写入 `org.opencontainers.image.base.name`，记录完整基础镜像引用。最终多平台 index 同样写入 version（如有）和 revision annotations，便于远程检查。

`latest` 与版本 tag 都允许更新：同一上游版本下的工具升级和重建会移动版本 tag。需要固定某次产物的消费者使用 digest，不使用 SHA tag。

### 远程 Git context

每个 target 的 `context` 使用 GitHub Git URL，例如：

```hcl
target "agent-vault" {
  context    = "https://github.com/YewFence/agent-vault.git?branch=main"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]
}
```

子目录使用 BuildKit Git URL 的 `subdir` query 参数：

```hcl
context = "https://github.com/YewFence/example.git?branch=main&subdir=container"
```

不再 checkout 上游源码。发布前每个 target 解析一次 context 的实际提交，并生成带 `ref=<完整 SHA>&checksum=<完整 SHA>` 的 Bake JSON；所有平台读取同一份计划，因此构建期间分支移动不会造成平台间源码不一致。context 指向当前编排仓库及本次 workflow ref 时使用本次 checkout 的提交，避免工作流排队期间 main 更新导致源码与版本解析错位。构建时仍由 BuildKit 拉取远程 context。

### 原生多平台构建

`docker/bake-action/subaction/matrix` 从 Bake target 的 `platforms` 属性生成矩阵。它会在 job 日志中输出完整的 Bake definition；当前私有配置只包含需要保护的上游仓库地址，后续再增加日志清理 action。每个平台 job 使用固定 runner 映射：

```text
linux/amd64 -> ubuntu-24.04
linux/arm64 -> ubuntu-24.04-arm
```

构建 job 只构建自己的平台，不启用 QEMU。发布时每个平台使用 `push-by-digest=true` 推送独立 manifest，并通过 GitHub artifact 传递 digest。最终的 `publish-manifest` job 使用 `docker buildx imagetools create` 给同一个多平台 manifest 添加 `latest` 和可选的上游版本 tag。

### GitHub App 认证

准备发布计划和各平台构建的 job 分别在 runner 内使用 `actions/create-github-app-token` 生成短期 installation token。需要配置：

- repository variable：`SOURCE_APP_CLIENT_ID`
- repository secret：`SOURCE_APP_PRIVATE_KEY`

GitHub App 必须对所有需要构建的上游仓库具有 `Contents: read` 权限，并安装到对应 owner。token 不写入 matrix、job output、artifact 或 Bake 文件；BuildKit 通过 `GIT_AUTH_TOKEN` secret 读取它。

## 仓库结构

```text
.
├── docker-bake.hcl
├── private-repo-bake.hcl.bin
├── .sops.yaml
├── .yewseal.toml
├── mise.toml
└── .github/
    └── workflows/
        └── build-images.yml
```

target 解析、平台展开和配置合并由 Docker Buildx Bake 负责；源码固定、版本解析和 manifest 发布由 mise 任务负责。workflow 传递矩阵、短期发布计划和平台 digest，不重复实现版本规则。

## 私有 Bake 配置

私有 target 保存在加密文件 `private-repo-bake.hcl.bin` 中。`.yewseal.toml` 定义明文和密文文件的对应关系，`.sops.yaml` 定义 Age recipient。明文文件 `private-repo-bake.hcl` 被 `.gitignore` 忽略，不会提交到仓库。

GitHub Actions repository secret 只需要提供：

```text
SOPS_AGE_KEY=<对应 Age recipient 的私钥>
```

默认分支的 `check` 和每个 target 的 `prepare-release` job 会把它设置为同名环境变量，然后直接运行 `yews decrypt`。PR 不读取该 secret，也不会解密私有配置。

解密后的 HCL 只需要包含新增的 target，例如：

```hcl
target "private-image" {
  context    = "https://github.com/YewFence/private-image.git?branch=main"
  dockerfile = "containers/Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]
}
```

workflow 会将解密文件与仓库内的 `docker-bake.hcl` 一起加载。没有手动指定 target 时，会根据两份配置合并后的 target 列表生成临时默认 group，因此新增的私有 target 会自动参与默认构建。

## 工作流设计

### `check` job

`check` job 在 pull request 或默认分支构建中运行，负责：

1. checkout 当前编排仓库。
2. 在非 pull request 事件中通过 `SOPS_AGE_KEY` 和 `yews decrypt` 解密私有 Bake 配置。
3. 将仓库 HCL 与解密后的私有 HCL 作为两个 Bake 文件加载。
4. 运行 `mise run test`。
5. 使用 Docker 官方 Bake matrix action 按 target 的 platforms 展开矩阵。没有手动选择 target 时，workflow 会根据两份 Bake 配置合并后的 target 列表生成临时 `generated-default` group。
6. 将完整平台矩阵和去重后的 target 矩阵写入 job output。

workflow_dispatch 的 `name` 输入直接作为 Bake target 名；空输入使用 `default` group。

### `smoke-build` job

`smoke-build` 只在 pull request 中运行。每个 matrix 项：

1. checkout 当前编排仓库。
2. 根据目标平台选择原生 GitHub-hosted runner。
3. 使用 Bake 读取 target 的远程 Git context。
4. 将输出覆盖为 `type=cacheonly`，不登录 GHCR、不推送镜像、不写发布 cache。

pull request 不读取 `SOPS_AGE_KEY`，不解密私有配置，也不创建 GitHub App token。来自 fork 的 pull request 因此不会接触发布凭据。

### `prepare-release` job

`prepare-release` 只在受信任的发布事件中运行，每个 target 执行一次：

1. checkout 编排仓库并解密私有 Bake 配置。
2. 使用 `images:prepare --source-only` 读取 context 的 owner 和仓库名，再创建仅限该仓库、具有 `permission-contents: read` 权限的 GitHub App token；App 不可用时沿用 `GITHUB_TOKEN` 访问公开源。
3. 运行 `mise run images:prepare <target> <directory>`，固定源码提交、解析版本、设置 labels 和 tags。
4. 将 `bake.json` 和 `release.json` 作为保留一天的 artifact 传给各平台构建和 manifest 发布；文件不包含 token，私有 target 的计划仍包含仓库地址，与现有 matrix 日志的保护范围一致。

### `publish` job

`publish` 等待发布计划准备完成，每个平台 matrix 项：

1. checkout 当前编排仓库并下载该 target 的发布计划。
2. 根据计划中的 owner 和仓库名创建 GitHub App installation token，仅授权该源码仓库的 contents 读取权限。
3. 将 `GIT_AUTH_TOKEN` 绑定到 Bake target 的 BuildKit secret。
4. 使用计划中的固定 context 和 OCI labels，在原生 runner 构建单个平台。
5. 以 `push-by-digest=true` 推送到 GHCR，不直接竞争标签。
6. 读取 Bake metadata 的 `containerimage.digest`，写入短期 GitHub artifact。

发布 job 的权限为：

```yaml
permissions:
  contents: read
  packages: write
```

GHCR 登录使用当前 workflow 的 `GITHUB_TOKEN`。

### `publish-manifest` job

该 job 等待所有平台构建完成，按 target 下载发布计划和 digest artifacts，运行 `mise run images:manifest <directory>`。有明确上游版本时，其底层发布命令等价于：

```bash
docker buildx imagetools create \
  --tag ghcr.io/yewfence/<target>:latest \
  --tag ghcr.io/yewfence/<target>:<upstream-version> \
  ghcr.io/yewfence/<target>@sha256:<amd64-digest> \
  ghcr.io/yewfence/<target>@sha256:<arm64-digest>
```

单平台 target 也使用相同流程，此时 manifest 只包含一个平台。任务同时添加 version（如有）和 revision index annotations；无明确版本时省略版本 tag。`--dry-run` 只输出命令 JSON，不访问注册表。

### `cleanup` job

cleanup 在 manifest 发布成功后按 target 运行，使用固定 commit 的 `snok/container-retention-policy`。配置 `tag-selection: untagged` 与 `cut-off: 7d`，仅删除超过七天且不再被保留的带 tag 镜像引用的未标记产物；所有带 tag 的版本保留，同一上游版本反复构建后失去 tag 的旧产物会被回收。

该 action 从 v3.1.0 起自动读取保留的带 tag 版本的多平台 index，并保护其引用的平台 manifest。读取 manifest 失败时会跳过该 package 的删除，避免误删仍被引用的镜像。使用现有 `GITHUB_TOKEN` 和精确 package 名；仓库须在 package 设置中拥有 Admin 权限。清理按时间窗口保留近期未标记产物，不再按未标记版本数量保留十个。

## 安全模型

### 信任内容

- 默认分支中的 `docker-bake.hcl` 和 workflow 是受信任的发布配置。
- 加密的 `private-repo-bake.hcl.bin` 和 `SOPS_AGE_KEY` 是受保护的发布输入。
- GitHub App private key 只用于生成短期 installation token。
- App 安装明确列出的上游仓库是允许的 Docker 构建输入。

### 强制约束

- pull request 事件绝不进入拥有 `packages: write` 的 job，也不读取 `SOPS_AGE_KEY` 或创建 GitHub App token。
- 上游 Git token 不写入 Bake HCL、matrix output、artifact 或 Dockerfile build arg。
- BuildKit 只通过预定义的 `GIT_AUTH_TOKEN` secret 获取远程 Git 认证。
- 不执行上游仓库中的 GitHub Actions；唯一允许的上游执行入口是 Dockerfile 构建。
- target、context、Dockerfile 和 platforms 来自受信任的仓库 HCL 或加密私有 HCL，不接受普通 workflow_dispatch 输入覆盖。
- 每个平台使用 GitHub 托管的一次性 runner，构建 job 之间不共享工作目录。
- 每个构建设置超时，避免异常构建长期占用 runner。

Bake HCL 是受信任配置，因此可以指定任意 BuildKit target、远程 context 和 output。Age 私钥只应配置为 GitHub Actions repository secret，并限制能够修改默认分支 workflow 的人员范围。

## 测试与验证

本地测试使用 `mise run test`，依赖由 `pyproject.toml` 与 `uv.lock` 管理。镜像发布测试覆盖 Dockerfile 版本解析、ARG 覆盖、精确 Git tag 匹配、annotated tag、源码 checksum、共享计划和多标签 manifest 命令。Bake 定义可以通过以下命令检查解析结果：

```bash
docker buildx bake --file docker-bake.hcl --print
```

发布前应使用一个小型 target 手动触发 workflow，确认：

1. amd64 job 使用 `ubuntu-24.04`。
2. arm64 job 使用 `ubuntu-24.04-arm`。
3. GitHub App token 能读取私有 Git context。
4. GHCR 的 `latest` 与版本 tag 指向同一个 digest，manifest 包含预期平台。
5. 镜像 config 的 version/revision labels 和 index annotations 与实际构建源码一致。
6. 无对应版本 tag 的分支构建只发布 `latest`，不误用最近 release 的版本。
7. cleanup 保留仍有 tag 的历史版本及其平台 manifest，并回收超过七天的无引用未标记产物。

## 参考资料

- [Container Retention Policy 的多平台镜像保护](https://github.com/snok/container-retention-policy#multi-platform-multi-arch-image-safety)
- [Docker Bake action](https://github.com/docker/bake-action)
- [Docker Buildx Bake 文件覆盖](https://docs.docker.com/build/bake/overrides/)
- [Docker Git context 认证](https://docs.docker.com/build/building/secrets/#git-authentication-for-remote-contexts)
- [Docker 多平台 GitHub Actions 构建](https://docs.docker.com/build/ci/github-actions/multi-platform)
- [GitHub App token action](https://github.com/actions/create-github-app-token)
- [GitHub Actions reusable workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)
