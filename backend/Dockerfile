FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    NODE_VERSION=22.23.3 \
    OPENCODE_VERSION=1.18.34

# ffmpeg：音视频合成/混音；fonts-noto-cjk：中文字体；curl：健康检查/下载
# Chromium 运行库：Remotion 无头渲染（chrome-headless-shell）所需
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg fonts-noto-cjk curl ca-certificates xz-utils unzip ripgrep procps \
      libnss3 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
      libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
      libasound2 libpango-1.0-0 libcairo2 libatspi2.0-0 libx11-xcb1 libxcb1 \
    && rm -rf /var/lib/apt/lists/*

# Node.js（Remotion / opencode 都依赖）；用官方二进制，避免 NodeSource 网络问题
RUN ARCH="$(dpkg --print-architecture)" \
    && case "$ARCH" in arm64) NODE_ARCH=arm64 ;; *) NODE_ARCH=x64 ;; esac \
    && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" -o /tmp/node.tar.xz \
    && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
    && rm /tmp/node.tar.xz \
    && node --version && npm --version

# opencode headless（agent 大脑）；npm 走国内镜像
ARG NPM_REGISTRY=https://registry.npmmirror.com
RUN npm config set registry "$NPM_REGISTRY" \
    && npm install -g "opencode-ai@${OPENCODE_VERSION}" \
    && opencode --version || true

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
# pip 走国内镜像（服务器在中国；如构建机在海外可传 --build-arg PIP_INDEX_URL=）
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install -i "$PIP_INDEX_URL" -r requirements.txt

COPY backend/ ./backend/
WORKDIR /app/backend

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
