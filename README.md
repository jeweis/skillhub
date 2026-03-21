# Skill Hub

Skill Hub 是一个面向 Claude Agent Skills 的轻量商店。

用户可以在这里浏览、搜索、查看说明、下载 Skills；创作者可以登录后发布自己的 Skills；管理员可以管理账号并配置飞书登录。

## 功能

- 浏览 Skill 列表
- 搜索 Skill
- 查看 Skill 详情和 Markdown 预览
- 下载 Skill 压缩包
- 登录后发布 Skill
- 管理员创建账号
- 管理员配置飞书登录

## 使用方式

启动后可访问：

- 首页：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/docs`

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

## 部署

当前部署方式是“前端产物提前构建并提交，线上只部署这个仓库”。

如果前端有更新，请先在 workspace 根目录执行：

```bash
bash ./scripts/build_frontend_to_backend.sh
```

然后构建镜像：

```bash
cd backend
docker build -t skillhub-backend:latest .
```

运行容器：

```bash
cd backend
docker run --rm -p 8000:8000 \
  -v "$(pwd)/data:/app/data" \
  -e APP_SECRET_KEY="replace-with-a-long-random-secret" \
  skillhub-backend:latest
```

或者使用 Docker Compose：

```bash
cd backend
docker compose up --build -d
```

部署后会同时提供：

- 站点页面：`http://127.0.0.1:8000`
- API：`http://127.0.0.1:8000/api/*`
- Swagger：`http://127.0.0.1:8000/docs`

## 数据持久化

默认数据会写到 [data](/Users/jewei/host_workspace/project/jewei/skills-hub-workspace/backend/data) 目录：

- 数据库：`data/skill_hub.db`
- Skill 压缩包：`data/archives/`

生产环境建议：

- 挂载 [data](/Users/jewei/host_workspace/project/jewei/skills-hub-workspace/backend/data) 到持久化存储
- 设置固定的 `APP_SECRET_KEY`
- 每次发布前确认 `app/static` 已更新到最新前端产物
