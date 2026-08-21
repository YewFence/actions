# 声明式容器镜像编排器设计

## 状态

- 阶段：已实现
- 目标仓库：`YewFence/actions`
- 目标注册表：GitHub Container Registry（GHCR）
- 发布命名空间：`ghcr.io/yewfence`

## 背景

本仓库使用 Docker Buildx Bake 作为镜像声明和构建入口。仓库内的 `docker-bake.hcl` 声明公开构建目标；Infisical OIDC action 可以在受信任的发布事件中注入额外的 Bake HCL，用于覆盖现有 target 或增加私有 target。Docker Bake 直接使用上游 Git 仓库作为构建 context，不再由 Actions checkout 上游源码。

## 目标

- 通过一个 Bake 定义增加、修改或停用镜像，不为每个镜像复制工作流。
- 从公开或私有的 GitHub 仓库构建镜像，并发布为 `ghcr.io/yewfence/<target>:latest`。
- 支持手动构建、默认分支构建和 pull request smoke build。
- 在 `ubuntu-24.04` 与 `ubuntu-24.04-arm` 上分别原生构建 amd64 和 arm64。
- 让 Docker Bake matrix action 解析 target 和平台，不再维护镜像矩阵转换器。
- 使用 GitHub App installation token 访问需要权限的上游 Git context。
- 保留发布 digest，并让最终的 `latest` 始终是多平台 manifest。

## 非目标

- 不监听上游仓库事件；上游更新通过下一次构建被拉取。
- 不发现或同步上游 release、Git tag 和语义化版本。
- 不发布除 `latest` 之外的用户可见版本标签。
- 不自动修改 GHCR package 的可见性或权限。
- 不自动判断第三方项目的许可证是否允许重新分发。

## 核心决策

### Docker Bake 是唯一构建配置

`docker-bake.hcl` 是公开构建配置的唯一事实来源。每个 target 的名称同时是 GHCR package 名和 workflow_dispatch 的选择值；target 内声明 Git context、Dockerfile、目标平台、标签和 OCI labels。

Bake 的多文件覆盖规则负责合并仓库配置和 Infisical 配置。后加载文件中的同名 target 可以覆盖或补充前一个文件中的属性；因此受保护的 Infisical HCL 可以增加私有镜像，也可以调整公开镜像的 source ref。

### 远程 Git context

每个 target 的 `context` 使用 GitHub Git URL，例如：

```hcl
target "agent-vault" {
  context    = "https://github.com/YewFence/agent-vault.git?branch=main"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]
  tags       = ["ghcr.io/yewfence/agent-vault:latest"]
}
```

子目录使用 BuildKit Git URL 的 `subdir` query 参数：

```hcl
context = "https://github.com/YewFence/example.git?branch=main&subdir=container"
```

不再 checkout 上游源码，因此 runner 工作目录中只需要当前编排仓库的 Bake 文件。构建时由 BuildKit 拉取远程 context。

### 原生多平台构建

`docker/bake-action/subaction/matrix` 从 Bake target 的 `platforms` 属性生成矩阵。每个平台 job 使用固定 runner 映射：

```text
linux/amd64 -> ubuntu-24.04
linux/arm64 -> ubuntu-24.04-arm
```

构建 job 只构建自己的平台，不启用 QEMU。发布时每个平台使用 `push-by-digest=true` 推送独立 manifest，并通过 GitHub artifact 传递 digest。最终的 `publish-manifest` job 使用 `docker buildx imagetools create` 生成 `latest` 多平台 manifest。

### GitHub App 认证

发布 job 在 runner 内使用 `actions/create-github-app-token` 生成短期 installation token。需要配置：

- repository variable：`SOURCE_APP_CLIENT_ID`
- repository secret：`SOURCE_APP_PRIVATE_KEY`

GitHub App 必须对所有需要构建的上游仓库具有 `Contents: read` 权限，并安装到对应 owner。token 不写入 matrix、job output、artifact 或 Bake 文件；BuildKit 通过 `GIT_AUTH_TOKEN` secret 读取它。

## 仓库结构

```text
.
├── docker-bake.hcl
├── mise.toml
└── .github/
    └── workflows/
        └── build-images.yml
```

target 解析、平台展开和配置合并由 Docker Buildx Bake 负责；workflow 只把矩阵和 digest 作为后续 job 的机器可读输出。

## Infisical 覆盖配置

Infisical 项目 `yew-fence-actions` 可以提供名为 `DOCKER_BAKE_HCL` 的多行 secret。该 secret 必须是合法的 Bake HCL，可以包含一个或多个 target，例如：

```hcl
target "private-image" {
  context    = "https://github.com/YewFence/private-image.git?branch=main"
  dockerfile = "containers/Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]
  tags       = ["ghcr.io/yewfence/private-image:latest"]
}

target "agent-vault" {
  context = "https://github.com/YewFence/agent-vault.git?branch=release"
}
```

`check` job 和每个发布平台 job 都独立运行 Infisical action，并在各自的 runner 临时目录写入 HCL 文件。check job 用合并后的 Bake 文件生成 target/platform matrix；发布 job 用同一份合并配置执行实际构建。runner job 结束后临时文件随一次性 runner 销毁。

Infisical action 使用 `continue-on-error: true`。Infisical 不可用时，工作流回退到仓库内的 `docker-bake.hcl`；这允许公开 target 继续构建，但本次不会发现或构建仅存在于 Infisical 中的私有 target。

## 工作流设计

### `check` job

`check` job 在 pull request 或默认分支构建中运行，负责：

1. checkout 当前编排仓库。
2. 在非 pull request 事件中通过 OIDC 读取 `DOCKER_BAKE_HCL`。
3. 将仓库 HCL 与 Infisical HCL 作为两个 Bake 文件加载。
4. 运行 `mise run test`。
5. 使用 Docker 官方 Bake matrix action 按 target 的 platforms 展开矩阵。没有手动选择 target 时，workflow 会根据 Bake 的 target 列表生成临时 `generated-default` group，因此 Infisical 新增的 target 不需要修改仓库内的 group。
6. 将完整平台矩阵和去重后的 target 矩阵写入 job output。

workflow_dispatch 的 `name` 输入直接作为 Bake target 名；空输入使用 `default` group。

### `smoke-build` job

`smoke-build` 只在 pull request 中运行。每个 matrix 项：

1. checkout 当前编排仓库。
2. 根据目标平台选择原生 GitHub-hosted runner。
3. 使用 Bake 读取 target 的远程 Git context。
4. 将输出覆盖为 `type=cacheonly`，不登录 GHCR、不推送镜像、不写发布 cache。

pull request 不读取 Infisical，不创建 GitHub App token。来自 fork 的 pull request 因此不会接触发布凭据。

### `publish` job

`publish` 不在 pull request 中运行。每个平台 matrix 项：

1. checkout 当前编排仓库。
2. 通过 Infisical 读取并物化合并 HCL。
3. 创建 GitHub App installation token。
4. 将 `GIT_AUTH_TOKEN` 绑定到 Bake target 的 BuildKit secret。
5. 使用原生 runner 构建单个平台。
6. 以 `push-by-digest=true` 推送到 GHCR，不直接竞争 `latest`。
7. 读取 Bake metadata 的 `containerimage.digest`，写入短期 GitHub artifact。

发布 job 的权限为：

```yaml
permissions:
  contents: read
  packages: write
  id-token: write
```

`id-token: write` 用于 Infisical OIDC；GHCR 登录使用当前 workflow 的 `GITHUB_TOKEN`。

### `publish-manifest` job

该 job 等待所有平台构建完成，按 target 下载 digest artifacts，并执行：

```bash
docker buildx imagetools create \
  --tag ghcr.io/yewfence/<target>:latest \
  ghcr.io/yewfence/<target>@sha256:<amd64-digest> \
  ghcr.io/yewfence/<target>@sha256:<arm64-digest>
```

单平台 target 也使用相同流程，此时 manifest 只包含一个平台。

### `cleanup` job

cleanup 使用去重后的 target 矩阵，仅在最终 manifest 发布成功后运行。它删除没有标签的旧 GHCR container versions，并保留最近两个版本。digest-only 平台 manifests 会在后续 cleanup 中被清理，不影响 `latest` manifest。

## 安全模型

### 信任内容

- 默认分支中的 `docker-bake.hcl` 和 workflow 是受信任的发布配置。
- Infisical 中的 `DOCKER_BAKE_HCL` 是受保护的发布输入。
- GitHub App private key 只用于生成短期 installation token。
- App 安装明确列出的上游仓库是允许的 Docker 构建输入。

### 强制约束

- pull request 事件绝不进入拥有 `packages: write` 的 job，也不执行 Infisical 或 App token action。
- 上游 Git token 不写入 Bake HCL、matrix output、artifact 或 Dockerfile build arg。
- BuildKit 只通过预定义的 `GIT_AUTH_TOKEN` secret 获取远程 Git 认证。
- 不执行上游仓库中的 GitHub Actions；唯一允许的上游执行入口是 Dockerfile 构建。
- target、context、Dockerfile、tags 和 platforms 来自受信任的仓库 HCL 或 Infisical 覆盖，不接受普通 workflow_dispatch 输入覆盖。
- 每个平台使用 GitHub 托管的一次性 runner，构建 job 之间不共享工作目录。
- 每个构建设置超时，避免异常构建长期占用 runner。

Bake HCL 是受信任配置，因此可以指定任意 BuildKit target、远程 context 和 output。Infisical 项目权限必须限制在发布维护者范围内。

## 测试与验证

本地测试使用 `mise run test`，覆盖仓库的 Python 逻辑。Bake 定义可以通过以下命令检查解析结果：

```bash
docker buildx bake --file docker-bake.hcl --print
```

发布前应使用一个小型 target 手动触发 workflow，确认：

1. amd64 job 使用 `ubuntu-24.04`。
2. arm64 job 使用 `ubuntu-24.04-arm`。
3. GitHub App token 能读取私有 Git context。
4. GHCR 的 `latest` manifest 同时包含预期平台。
5. manifest digest 正常生成。
6. cleanup 只删除未标记的旧版本。

## 参考资料

- [Docker Bake action](https://github.com/docker/bake-action)
- [Docker Buildx Bake 文件覆盖](https://docs.docker.com/build/bake/overrides/)
- [Docker Git context 认证](https://docs.docker.com/build/building/secrets/#git-authentication-for-remote-contexts)
- [Docker 多平台 GitHub Actions 构建](https://docs.docker.com/build/ci/github-actions/multi-platform)
- [GitHub App token action](https://github.com/actions/create-github-app-token)
- [GitHub Actions reusable workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)
