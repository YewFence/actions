group "default" {
  targets = ["agent-vault", "resticprofile-runner", "restic-exporter", "mltb"]
}

target "restic-exporter" {
  context    = "https://github.com/YewFence/actions.git?branch=main&subdir=images/restic-exporter"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]

  labels = {
    "org.opencontainers.image.source" = "https://github.com/YewFence/actions"
  }
}

target "resticprofile-runner" {
  context    = "https://github.com/YewFence/actions.git?branch=main&subdir=images/resticprofile-runner"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]

  labels = {
    "org.opencontainers.image.source" = "https://github.com/YewFence/actions"
  }
}

target "agent-vault" {
  context    = "https://github.com/YewFence/agent-vault.git?branch=main"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]

  labels = {
    "org.opencontainers.image.source" = "https://github.com/YewFence/agent-vault"
  }
}

target "mltb-base" {
  # anasty17/mltb 官方 base 镜像的构建脚本藏在 BuildKit secret 里（docker history 不可见）；
  # 改用社区透明重建版（MIT，见 docs/REVERSE-ENGINEERING.md）。仅 ship 运行时与下载工具链，bot 源码由 mltb target 叠加。
  # 注意：该 Dockerfile 的 rclone 段硬编码 linux-amd64，不要给本 target 加 arm64。
  context    = "https://github.com/botsgalaxy/mltb-docker-base.git?branch=main"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]

  labels = {
    "org.opencontainers.image.source" = "https://github.com/botsgalaxy/mltb-docker-base"
  }
}

target "mltb" {
  # mirror-leech-telegram-bot 本体没有版本化 release；直接用上游 master 构建，无需 fork。
  # 上游 Dockerfile 的 FROM anasty17/mltb:latest 经 named context 替换为自建 mltb-base，
  # 绕开不透明的官方 base 镜像；更新走重新 dispatch build-images。
  context    = "https://github.com/anasty17/mirror-leech-telegram-bot.git?branch=master"
  dockerfile = "Dockerfile"
  contexts = {
    "anasty17/mltb:latest" = "target:mltb-base"
  }
  platforms  = ["linux/amd64"]

  labels = {
    "org.opencontainers.image.source" = "https://github.com/anasty17/mirror-leech-telegram-bot"
  }
}

