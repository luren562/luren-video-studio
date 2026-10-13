#!/usr/bin/env bash
# 更新已部署实例：解压新源码包后运行本脚本（保留 .env 与 engines/）
# 用法：cd /www/wwwroot/web && bash deploy/update.sh
set -euo pipefail
cd "$(dirname "$0")/.."
echo "==> 重新构建并启动（复用 .env / engines / media_data 卷）"
docker compose up --build -d
echo "==> 容器状态"
docker compose ps
echo "==> api 最近日志"
docker compose logs --tail=60 api
