# resticprofile 备份 runner 镜像。
# 官方镜像只含 restic / rclone / resticprofile，不含 supercronic；
# 上游文档的容器调度模式就是在此基础上自行派生镜像加 supercronic 做前台调度。
# 消费方：services 仓库的 edge/resticprofile 与 stump/backup-ops。
FROM creativeprojects/resticprofile:0.33.1@sha256:c8afc532eb7693908ca8f0f0a791f632098268ec8ab1b4b63af1a642894a6ad7

RUN apk add --no-cache supercronic
