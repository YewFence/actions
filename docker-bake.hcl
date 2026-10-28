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
  platforms  = ["linux/amd64"]

  labels = {
    "org.opencontainers.image.source" = "https://github.com/YewFence/agent-vault"
  }
}

