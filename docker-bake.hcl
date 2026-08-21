group "default" {
  targets = ["agent-vault"]
}

target "agent-vault" {
  context    = "https://github.com/YewFence/agent-vault.git?branch=main"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]

  tags = [
    "ghcr.io/yewfence/agent-vault:latest",
  ]

  labels = {
    "org.opencontainers.image.source" = "https://github.com/YewFence/agent-vault"
  }
}
