# skill-hub-backend

Skill Hub 后端服务目录。

当前后端围绕一个极简 Skill Hub 模型组织数据：上传 zip、解析 `SKILL.md`、存储可预览 Markdown、提供 zip 下载。

当前该目录直接存在于 workspace 中，作为未来独立子仓库 `skill-hub-backend` 的本地占位实现。后续具备远程仓库后，可迁移为真正的 git submodule。

## 技术栈

- FastAPI
- SQLite
- uv
- pytest

## 本地运行

```bash
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 测试

```bash
uv run pytest
```

## 数据库

默认数据库文件位于：

```text
data/skill_hub.db
```

应用启动时会自动初始化表结构。

## Docker 部署

当前项目采用“前端提前构建、产物随仓库提交”的方式部署。

也就是说：

- 前端 Web 产物需要先构建并同步到 [app/static](/Users/jewei/host_workspace/project/jewei/skills-hub-workspace/backend/app/static)
- Docker 镜像只打包后端目录
- 容器启动后会同时提供 API 和站点页面

如果前端有更新，发布镜像前请先在 workspace 根目录执行：

```bash
bash ./scripts/build_frontend_to_backend.sh
```

确认最新静态文件已经进入 `backend/app/static` 后，再继续下面的 Docker 构建。

### 构建镜像

```bash
cd backend
docker build -t skillhub-backend:latest .
```

### 运行容器

```bash
cd backend
docker run --rm -p 8000:8000 \
  -v "$(pwd)/data:/app/data" \
  -e APP_SECRET_KEY="replace-with-a-long-random-secret" \
  skillhub-backend:latest
```

### 使用 docker compose

```bash
cd backend
docker compose up --build -d
```

容器会直接对外提供：

- 首页：`http://127.0.0.1:8000`
- API：`http://127.0.0.1:8000/api/*`
- Swagger：`http://127.0.0.1:8000/docs`

### 数据持久化

`docker-compose.yml` 已将宿主机目录 `backend/data` 挂载到容器内 `/app/data`，这里会保存：

- SQLite 数据库
- 上传的 skill zip 压缩包

如果需要启用飞书登录，生产环境建议设置固定的 `APP_SECRET_KEY`，用于加密保存飞书 `App Secret`。
