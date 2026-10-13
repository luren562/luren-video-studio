#!/usr/bin/env bash
# Video Foundry 一键部署（Ubuntu 24.04 / 宝塔面板环境）
# 用法：把 web_src.tar.gz 解压后，在 web/ 目录执行：  bash deploy/install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
echo "==> 项目目录：$ROOT"

# ---------- 1. Docker ----------
echo "==> [1/5] 检查 Docker / Compose"
if ! command -v docker >/dev/null 2>&1; then
  echo "    安装 Docker（官方脚本）..."
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "    安装 docker compose 插件..."
  apt-get update -y && apt-get install -y docker-compose-plugin || true
fi
docker --version
docker compose version

# ---------- 2. 引擎（GitHub 克隆） ----------
echo "==> [2/5] 克隆引擎到 ./engines/"
command -v git >/dev/null 2>&1 || { apt-get update -y && apt-get install -y git; }
mkdir -p engines
# 服务器在中国时若 GitHub 拉取失败，可加代理前缀，例如：
#   GH_PROXY=https://ghfast.top/ bash deploy/install.sh
GH_PROXY="${GH_PROXY:-}"
clone() {
  local dir="$1" url="$2"
  if [ ! -d "engines/$dir/.git" ]; then
    git clone --depth 1 "${GH_PROXY}${url}" "engines/$dir" \
      || { echo "    !! 克隆 $dir 失败；若是网络问题，请用 GH_PROXY=https://ghfast.top/ 重试"; exit 1; }
  else
    (cd "engines/$dir" && git fetch --depth 1 origin && git reset --hard FETCH_HEAD) || true
  fi
}
clone video-shotcraft    https://github.com/Vincentwei1021/video-shotcraft.git
clone video-talkcraft    https://github.com/Vincentwei1021/video-talkcraft.git
clone anything2explainer https://github.com/Vincentwei1021/anything2explainer.git

# ---------- 3. .env（自动生成密钥） ----------
echo "==> [3/5] 生成 .env"
if [ ! -f .env ]; then
  JWT="$(openssl rand -hex 32)"
  FERNET="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')"
  ADMIN_PW="123456"
  cat > .env <<EOF
DATABASE_URL=sqlite:////app/backend/data/backend.db
JWT_SECRET=${JWT}
FERNET_KEY=${FERNET}
ADMIN_USERNAME=admin
ADMIN_PASSWORD=${ADMIN_PW}
CORS_ORIGINS=["http://127.0.0.1:8080"]
WEB_PORT=8080
AI_BASE_URL=
AI_API_KEY=
AI_MODEL=
TTS_ENABLED=true
TTS_PROVIDER=edge
TTS_FALLBACK=none
AGENT_FILM_ENABLED=true
AGENT_OPENCODE_ENABLED=true
EOF
  echo "    ----------------------------------------------"
  echo "    管理员账号：admin"
  echo "    管理员密码：${ADMIN_PW}（首次登录后请尽快修改）"
  echo "    ----------------------------------------------"
else
  echo "    .env 已存在，跳过生成"
fi

# ---------- 4. 构建并启动 ----------
echo "==> [4/5] 构建镜像并启动（首次较慢，需要几分钟）"
docker compose up --build -d

# ---------- 5. 访问入口（直接占用 80，停用宝塔 nginx 以免冲突） ----------
echo "==> [5/5] 配置访问入口"
pkill -f 'nginx: master' 2>/dev/null || true
sleep 1
if curl -fsS "http://127.0.0.1/" >/dev/null 2>&1; then
  echo "    应用已在 80 端口就绪"
else
  echo "    警告：80 暂未响应，请查看：docker compose logs -f api"
fi

echo ""
echo "==================== 部署完成 ===================="
echo "  访问：http://$(curl -fsS --max-time 5 ifconfig.me 2>/dev/null || echo '服务器IP')/"
echo "  管理员：admin / 见上面的随机密码（也可在 .env 查看 ADMIN_PASSWORD）"
echo "  下一步：登录后到「AI 供应商」添加你的 OpenAI 兼容网关与模型，才能开始制作。"
echo "==================================================="
