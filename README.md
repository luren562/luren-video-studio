# 路仁视频工作室 · Video Foundry

> 让灵感成为作品 —— 从选题、AI 脚本分镜，到 Agent 自动制作与成片管理的一站式 AI 视频创作工作台。

路仁视频工作室（Video Foundry）是一个可自托管的 AI 短视频生产系统：你给出创作需求，系统驱动 AI 代理读取「制作引擎」的技能文档，自动生成分镜、写中文旁白、合成配音与字幕、用 Remotion 渲染出成片，并统一管理素材、任务与输出。

## 功能特性

- **端到端制作**：选题 → 脚本/分镜 → 素材 → 配音/字幕 → Remotion 渲染 → 成片与封面，全流程可视化。
- **双引擎**：`video-shotcraft`（信息图 / 图文类短视频）与 `video-talkcraft`（口播类竖屏视频）。
- **中文配音（免费）**：内置 **Edge TTS**，14 个中文音色、免登录、词级时间戳；也可上传自己的旁白音频配字幕。
- **AI 供应商无关**：兼容任意 OpenAI 协议的网关，文本 / 视觉 / 图片 / Agent 模型按能力（capability）分配。
- **本地转写**：基于 faster-whisper 把视频 / 音频转成文稿。
- **自动主题封面**：渲染成功后按主题色生成封面（需配置生图模型）。
- **实时进度**：任务队列 + SSE 推送，单机串行处理。
- **单机部署**：Docker Compose 一键起。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | Vue 3 + Vite + TypeScript + Pinia + Vue Router |
| 后端 | FastAPI + SQLAlchemy 2 + Alembic；默认 SQLite，可切 PostgreSQL |
| Agent | [opencode](https://opencode.ai) headless，读取引擎 skill 生成 Remotion 工程 |
| 配音 | edge-tts（免费）+ 人工旁白上传 |
| 渲染 | Remotion（Node） + FFmpeg |
| 部署 | Docker Compose + Nginx |

## 快速开始（Docker）

前置：Docker、Docker Compose、git。

```bash
# 1. 获取代码
git clone <你的仓库地址> video-foundry
cd video-foundry

# 2. 准备环境变量（首次会自动生成，也可手动复制后修改）
cp .env.example .env

# 3. 构建并启动（首次较慢，需要拉取引擎与依赖）
docker compose up --build -d

# 4. 打开浏览器
#    http://<服务器IP>/
```

或使用一键脚本（会自动 clone 引擎、生成 `.env`、停用冲突的 nginx）：

```bash
bash deploy/install.sh
```

**默认管理员账号：`admin` / `123456`（首次登录后请立即修改）。**

> TTS 默认使用 Edge（免费、免登录），开箱即用。若要使用高质量模型或私有网关，登录后在
> 「设置 → AI 供应商」里配置即可。

## 本地开发

**后端：**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**前端：**

```bash
cd frontend
npm install
npm run dev        # 默认 5173，/api 已代理到 http://127.0.0.1:8000
```

**校验：**

```bash
cd backend && pytest            # 后端测试
cd frontend && npm run typecheck # 前端类型检查
```

## 配置说明（`.env`）

| 变量 | 说明 |
| --- | --- |
| `JWT_SECRET` | 登录令牌签名密钥，生产环境务必修改 |
| `FERNET_KEY` | 敏感配置加密密钥（如 API Key 落库），留空则从 `JWT_SECRET` 派生 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 初始管理员账号，默认 `admin` / `123456` |
| `DATABASE_URL` | 默认 SQLite；可改为 PostgreSQL 连接串 |
| `AI_BASE_URL` / `AI_API_KEY` / `AI_MODEL` | OpenAI 兼容网关默认值（也可在「设置」页配置） |
| `TTS_PROVIDER` | 配音引擎，开源版仅支持 `edge`（免费）与 `manual`（人工旁白） |
| `TTS_VOICE_ZH` | 默认中文音色，默认 `zh-CN-YunxiNeural` |
| `COVER_ENABLED` | 是否在渲染成功后自动生成主题封面 |

完整列表见 `.env.example`。

## 目录结构

```
.
├── backend/            # FastAPI 后端
│   ├── app/            # 业务代码（routers / agent / tts / ...）
│   ├── migrations/     # Alembic 迁移
│   ├── agent_scripts/  # 注入到 Agent 工作区的 Node 命令
│   └── tests/
├── frontend/           # Vue 3 前端
├── deploy/             # 部署脚本与 nginx 配置
├── engines/            # 制作引擎（运行时挂载，不提交内容）
└── docker-compose.yml
```

## 致谢

本项目的制作能力由以下优秀开源项目驱动，特此致谢（制作引擎在运行时克隆接入，不包含在本仓库内）：

- [video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft) —— 信息图 / 图文类短视频制作引擎
- [video-talkcraft](https://github.com/Vincentwei1021/video-talkcraft) —— 口播类竖屏视频制作引擎
- [anything2explainer](https://github.com/Vincentwei1021/anything2explainer) —— 从内容到解说视频的模板与脚本

以及 [opencode](https://opencode.ai)、[Remotion](https://www.remotion.dev/)、[edge-tts](https://github.com/rany2/edge-tts) 等开源项目。再次感谢以上作者的无私分享。

## 反馈交流

有问题、建议，或想跟进后续更新，欢迎加入 QQ 交流群：**306884758**

<img src="frontend/public/qq-group.jpg" alt="QQ 交流群 306884758" width="240" />

## 许可证

[MIT](LICENSE)
