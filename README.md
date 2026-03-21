# Skill Hub

Skill Hub 是一个面向 Claude Agent Skills 的轻量商店。

用户可以在这里浏览、搜索、查看说明、下载 Skills；创作者可以登录后发布自己的 Skills；管理员可以管理账号并配置飞书登录。

当前仓库同时承担了 Skill Hub 的运行入口：既提供 API，也直接对外提供前端 Web 页面。

## 功能

- 浏览 Skill 列表
- 搜索 Skill
- 查看 Skill 详情和 Markdown 预览
- 下载 Skill 压缩包
- 登录后发布 Skill
- 管理员创建账号
- 管理员配置飞书登录
- 同时托管前端 Web 构建产物

## 技术栈

- Python 3.11
- FastAPI
- SQLite
- uv
- pytest

## 目录说明

- [app](/Users/jewei/host_workspace/project/jewei/skills-hub-workspace/backend/app)：应用代码与 API
- [app/static](/Users/jewei/host_workspace/project/jewei/skills-hub-workspace/backend/app/static)：站点前端静态页面
- [data](/Users/jewei/host_workspace/project/jewei/skills-hub-workspace/backend/data)：数据库和上传文件
- [tests](/Users/jewei/host_workspace/project/jewei/skills-hub-workspace/backend/tests)：测试

## 本地运行

安装依赖：

```bash
uv sync
```

启动服务：

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动后可访问：

- 首页：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/docs`

## 测试

```bash
uv run pytest
```

## 数据存储

默认数据会写到 [data](/Users/jewei/host_workspace/project/jewei/skills-hub-workspace/backend/data) 目录：

- 数据库：`data/skill_hub.db`
- Skill 压缩包：`data/archives/`

## 前端静态资源

Skill Hub 会直接从这个仓库对外提供前端页面，因此生产部署前需要确保 [app/static](/Users/jewei/host_workspace/project/jewei/skills-hub-workspace/backend/app/static) 中已经包含最新的前端构建产物。

当前项目约定是：

- 前端在开发阶段完成构建
- 构建产物同步到 `backend/app/static`
- 与后端代码一起提交
- Docker 部署时只部署后端

如果前端有更新，请先在 workspace 根目录执行：

```bash
bash ./scripts/build_frontend_to_backend.sh
```

然后再发布后端镜像。

## 账号与权限

- 未登录用户可以浏览、搜索、查看详情和下载 Skill
- 登录用户可以发布 Skill
- 管理员可以创建账号
- 管理员可以配置飞书登录

首次启动后，如果系统里还没有管理员账号，需要先完成管理员初始化。

## 飞书登录配置

管理员登录后，可以在管理界面配置：

- `App ID`
- `App Secret`
- `Base URL`

如果启用飞书登录，生产环境建议设置固定的 `APP_SECRET_KEY`，用于加密存储飞书 `App Secret`。

## Docker 部署

当前部署方式是“前端产物提前构建并提交，线上只部署这个仓库”。

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

### 使用 Docker Compose

```bash
cd backend
docker compose up --build -d
```

容器启动后会同时提供：

- 站点页面：`http://127.0.0.1:8000`
- API：`http://127.0.0.1:8000/api/*`
- Swagger：`http://127.0.0.1:8000/docs`

## 部署建议

- 挂载 [data](/Users/jewei/host_workspace/project/jewei/skills-hub-workspace/backend/data) 到持久化存储
- 为生产环境设置固定的 `APP_SECRET_KEY`
- 每次发布前先确认 `app/static` 已更新到最新前端产物
