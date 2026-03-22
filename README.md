<p align="center">
  <img src="app/static/favicon.png" alt="Skill Hub logo" width="140" />
</p>

# Skill Hub

Skill Hub 是一个面向 Claude Agent Skills 的轻量商店。

用户可以在这里浏览、搜索、查看说明、下载 Skills；创作者可以登录后发布自己的 Skills；管理员可以管理账号并配置飞书登录。

## 快速开始

构建镜像：

```bash
docker build -t skillhub:latest .
```

运行容器：

```bash
docker run -d \
  --name skillhub \
  --restart unless-stopped \
  -p 9509:8000 \
  -v "$(pwd)/data:/app/data" \
  -e APP_SECRET_KEY="replace-with-a-long-random-secret" \
  skillhub:latest
```

或者使用 Docker Compose：

```bash
docker compose up --build -d
```

启动后可访问：

- 首页：`http://127.0.0.1:9509`
- API 文档：`http://127.0.0.1:9509/docs`

## 功能

- 浏览 Skill 列表
- 搜索 Skill
- 查看 Skill 详情和 Markdown 预览
- 下载 Skill 压缩包
- 登录后发布 Skill
- 管理员创建账号
- 管理员配置飞书登录

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

## 数据持久化

默认数据会写到 [data](/Users/jewei/host_workspace/project/jewei/skills-hub-workspace/backend/data) 目录：

- 数据库：`data/skill_hub.db`
- Skill 压缩包：`data/archives/`

生产环境建议：

- 挂载 [data](/Users/jewei/host_workspace/project/jewei/skills-hub-workspace/backend/data) 到持久化存储
- 设置固定的 `APP_SECRET_KEY`
- 发布前确认站点静态资源和服务代码都已准备完成

## 本地启动

如果你想直接在本地运行，而不是通过 Docker，可以执行：

```bash
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动后可访问：

- 首页：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/docs`
