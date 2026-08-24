group "default" {
  targets = ["agent-vault", "komodo-core", "komodo-periphery", "komodo-cli"]
}

target "agent-vault" {
  context    = "https://github.com/YewFence/agent-vault.git?branch=main"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]

  labels = {
    "org.opencontainers.image.source" = "https://github.com/YewFence/agent-vault"
  }
}

target "komodo-core" {
  context    = "https://github.com/YewFence/komodo.git?branch=main"
  dockerfile = "fork.Dockerfile"
  target     = "core"
  platforms  = ["linux/amd64", "linux/arm64"]

  labels = {
    "org.opencontainers.image.source" = "https://github.com/YewFence/komodo"
  }
}

target "komodo-periphery" {
  context    = "https://github.com/YewFence/komodo.git?branch=main"
  dockerfile = "fork.Dockerfile"
  target     = "periphery"
  platforms  = ["linux/amd64", "linux/arm64"]

  labels = {
    "org.opencontainers.image.source" = "https://github.com/YewFence/komodo"
  }
}

target "komodo-cli" {
  context    = "https://github.com/YewFence/komodo.git?branch=main"
  dockerfile = "fork.Dockerfile"
  target     = "cli"
  platforms  = ["linux/amd64", "linux/arm64"]

  labels = {
    "org.opencontainers.image.source" = "https://github.com/YewFence/komodo"
  }
}
