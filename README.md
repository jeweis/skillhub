# skills-hub-backend

Skills Hub 后端服务目录。

当前后端围绕一个极简 skills hub 模型组织数据：上传 zip、解析 `SKILL.md`、存储可预览 Markdown、提供 zip 下载。

当前该目录直接存在于 workspace 中，作为未来独立子仓库 `skills-hub-backend` 的本地占位实现。后续具备远程仓库后，可迁移为真正的 git submodule。

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
data/skills_hub.db
```

应用启动时会自动初始化表结构。
