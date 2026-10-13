# engines/

引擎以**软链/挂载**方式接入，不把其仓库内容提交进本仓库。

开发机（Windows，管理员 PowerShell 或开启开发者模式）：

```powershell
New-Item -ItemType Junction -Path "video-shotcraft" -Target "<引擎仓库本地路径>"
```

或使用符号链接（Linux/macOS）：

```bash
ln -s ../../video-shotcraft ./video-shotcraft
```

Docker 部署时由 `docker-compose.yml` 直接只读挂载到容器内 `/engines`，无需在本目录创建链接。
一键部署脚本 `deploy/install.sh` 会把所需引擎克隆到本目录。

引擎的目录名与能力定义见 `backend/app/engine_registry.py`。
