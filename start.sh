#!/usr/bin/env bash
# 一键启动脚本：docker compose 的薄封装，顺带等到服务真正可用
set -e

cd "$(dirname "$0")"

if ! command -v docker &> /dev/null; then
  echo "没有找到 docker，请先安装 Docker Desktop 或 Docker Engine。"
  exit 1
fi

[ -f .env ] || { cp .env.example .env; echo "已生成 .env（用的是默认配置）"; }

echo "正在启动服务（首次运行需要下载模型，可能要几分钟）…"
docker compose up -d --build

PORT=$(grep -E '^WEB_PORT=' .env | cut -d= -f2)
PORT=${PORT:-8080}

echo "等待后端和模型就绪…"
for i in $(seq 1 90); do
  if curl -fs "http://localhost:${PORT}/api/health" > /dev/null 2>&1; then
    echo ""
    echo "全部就绪，打开 http://localhost:${PORT}"
    exit 0
  fi
  printf "."
  sleep 5
done

echo ""
echo "等待超时。模型可能还在下载，看一下日志："
echo "  docker compose logs -f ollama-init"
echo "  curl http://localhost:${PORT}/api/health"
