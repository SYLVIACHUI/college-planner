# 大学生日程表 AI Agent · 第一版

开启docker docker compose start
这一版分两部分：

1. **`index.html`** —— 一个可以直接打开看效果的交互原型（Vue 3，单文件，无需安装任何东西）。
   左侧拖拽日程块、中间周视图、点击编辑标题和备注、右侧 AI 分析，都已经能跑通。
   数据目前存在浏览器内存里，刷新页面会清空 —— 这一步是为了让你先确认交互和视觉方向对不对。

2. **`backend/`** —— 对应的 Python + MySQL 后端骨架，接口结构已经和前端的数据模型对齐，
   等你确认原型效果后，可以直接在这个基础上把前端原型改造成真正的 Vue 工程（vue-cli / vite），
   用 axios 调这些接口，替换掉现在内存存储的部分。

## 先看效果

直接用浏览器打开 `index.html` 即可，不需要安装依赖、不需要起服务。

体验重点：
- 左侧色块（学习/健身/作业/社交/娱乐/休息/其他）可以拖到中间表格的任意一个小时格子里
- 放入表格后的日程块也可以再拖动，改到别的时间格
- 点击已放入的日程块 → 弹窗里修改标题（比如"高等数学""爬坡训练"）、写备注
- 点右上角"AI 分析" → 会把你放入的日程和备注发给 Claude，返回时间分配的观察和建议
  （走本地 Ollama，不需要联网也不需要 API key；分析内容完全基于你已填写的备注，不会编造）

## 后端骨架（backend/）

```
backend/
├── schema.sql        # MySQL 表结构：users / categories / schedule_blocks / ai_analyses
├── app.py             # Flask 接口：类别、日程块增删改查、AI 分析
├── requirements.txt
└── .env.example
```

### 本地跑起来

```bash
cd backend
python -m venv venv && source venv/bin/activate   # Windows 用 venv\Scripts\activate
pip install -r requirements.txt

mysql -u root -p < schema.sql          # 建库建表，会自动插入 7 个默认类别

cp .env.example .env                    # 填入你的 MySQL 密码和 ANTHROPIC_API_KEY
python app.py                           # 默认跑在 http://127.0.0.1:5000
```

### 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/categories` | 获取全部日程类别（含颜色、emoji） |
| GET | `/api/blocks?user_id=1` | 获取某用户本周所有已放入的日程块 |
| POST | `/api/blocks` | 拖入新日程块：`{user_id, day_of_week, hour, category_key, title, notes}` |
| PUT | `/api/blocks/<id>` | 改标题/备注，或改 `day_of_week`/`hour` 实现"移动" |
| DELETE | `/api/blocks/<id>` | 删除某个日程块 |
| POST | `/api/ai/analyze?user_id=1` | 汇总该用户的日程+备注，调用 Claude 返回分析文本，并存一份历史记录 |
| POST | `/api/ai/chat` | **对话问答**：`{user_id, message, session_id, history, blocks}` → `{reply}` |
| GET | `/api/ai/chat/history?user_id=1&session_id=default` | 取某个会话的历史消息 |
| DELETE | `/api/ai/chat/history` | 清空某个会话的历史消息 |

`day_of_week` 用 1-7 表示周一到周日，`hour` 用 0-23。数据库里对 `(user_id, day_of_week, hour)` 做了唯一约束，
所以同一个格子重复插入会自动覆盖，正好对应"拖拽替换"的交互。

## 下一步建议

1. 确认原型的交互和视觉方向没问题后，把 `index.html` 里的 Vue 逻辑拆成正式的 Vue 工程
   （建议用 Vite：`npm create vite@latest planner-web -- --template vue`），
   把内存里的 `blocks` 换成对上面这些接口的 axios 调用。
2. 补上登录/用户体系（现在后端先用一个固定 `user_id` 占位）。
3. 如果想要"AI 主动提醒"之类更 agent 化的能力（比如检测到某天学习时间连续过长时主动提示），
   可以在 `ai_analyze` 里加规则判断，或者单独起一个定时任务调用同一个 prompt 逻辑。

先跑一下原型，告诉我哪些交互或样式需要调整，我再继续往下做。

## AI 对话助手（新增）

原来右侧抽屉只能点一次"AI 分析"看一段文本，现在它是一个可以**连续提问**的助手：
用户在输入框里问什么都可以，后端会把问题、之前的对话、以及当前日程表内容一起发给 Claude。

### 几个关键点

- **模型全部本地跑。** AI 部分已从 Anthropic 换成本地 Ollama（默认 qwen3:4b），
  不需要任何云端 API key，也不产生调用费用，断网也能用。
- **日程作为上下文。** 每次提问都会把表格内容拼成文本塞进 system prompt，
  所以用户问"我周三排太满了吗"，模型看得到周三到底有什么。
- **前端目前还没接 `/api/blocks`**，日程仍存在浏览器内存里，所以请求里带了一个 `blocks` 快照字段。
  等你把前端改造成真正的 Vue 工程、日程走数据库之后，把 `blocks` 去掉即可 ——
  后端 `resolve_blocks()` 会自动回落到查数据库，不用改接口。
- **历史消息**存进新表 `ai_chat_messages`，用 `session_id` 分会话；发给模型的只取最近 20 条，避免 token 无限增长。

### 使用前

`schema.sql` 需要重新执行一次（新增了 `ai_chat_messages` 表，以及一条 `id=1` 的演示用户记录）。
补充说明：原来的建表脚本没有插入用户，而 `schedule_blocks`、`ai_analyses` 都对 `users(id)` 有外键，
所以用默认的 `user_id=1` 写入时会直接报外键错误 —— 这次一并修掉了。

```bash
mysql -u root -p < schema.sql
python app.py
```

然后浏览器打开 `index.html`，右上角"AI 分析"或者直接在抽屉底部输入框提问。
注意 `index.html` 顶部的 `API_BASE` 默认是 `http://127.0.0.1:5000`，部署时改成你的服务器地址。

### 下一步可以做的

- 流式输出（SSE）：现在是等模型全部生成完才返回，长回答会等几秒；
  改成 `client.messages.stream()` + `text/event-stream` 就能像打字机一样逐字显示。
- 让 AI 能**直接改日程**：给模型加 tool use，定义 `create_block` / `delete_block` 两个工具，
  用户说"帮我周四晚上加两小时复习"，模型直接调接口写进数据库。这一步做完才算真正的 agent。
- 加频率限制，别让一个用户把 API 额度刷光。

---

# Docker 一键部署（Ollama + qwen3:4b）

AI 部分已改为本地 Ollama，不再依赖任何云端服务和 API key。

## 启动

```bash
./start.sh
```

或者手动：

```bash
cp .env.example .env
docker compose up -d --build
```

首次启动会自动下载 qwen3:4b（约 2.5GB），根据网速可能要几分钟。
下载进度：`docker compose logs -f ollama-init`

就绪后访问 **http://localhost:8080**

## 起了哪些容器

| 服务 | 作用 |
|---|---|
| `mysql` | 数据库，首次启动自动执行 `schema.sql` 建表 |
| `ollama` | 本地大模型运行时 |
| `ollama-init` | 一次性任务：拉 qwen3:4b，拉完自动退出 |
| `backend` | Flask 接口，gunicorn 跑 |
| `web` | nginx，托管 `index.html` + 把 `/api` 反代到后端 |

因为 nginx 做了反代，前端和接口**同源**，所以 `index.html` 里的 `API_BASE` 是空字符串，
不存在跨域问题。你也可以继续直接双击打开 `index.html`，代码会自动回落到 `http://127.0.0.1:5000`。

## 确认状态

```bash
curl http://localhost:8080/api/health
```

返回里 `db`、`ollama`、`model_ready` 三个都为 `true` 才算完全就绪。
`model_ready` 为 false 说明模型还在下载。

## 换模型

改 `.env` 里的 `OLLAMA_MODEL`（比如 `qwen3:8b`），然后：

```bash
docker compose up -d
```

`ollama-init` 会自动拉新模型。模型存在 named volume 里，容器重建不会重新下载。

## 关于 qwen3 的"思考模式"

qwen3 是混合推理模型，默认会先输出一段 `<think>...</think>` 的推理过程再给答案。
这段不能直接显示给用户，后端做了两层处理：

1. 请求里传 `"think": false` 关掉思考（老版本 Ollama 不认这个字段，代码里会自动去掉重试）；
2. `strip_thinking()` 兜底，用正则把 `<think>` 块剥掉，同时处理标签被截断的边界情况。

## GPU 加速

有 NVIDIA 显卡的话，把 `docker-compose.yml` 里 `ollama` 服务下面那段 `deploy:` 注释取消掉，
需要先装 nvidia-container-toolkit。4b 模型纯 CPU 也能跑，就是慢一些（一次回答十几秒到半分钟）。

## 常用命令

```bash
docker compose logs -f backend    # 看后端日志
docker compose restart backend    # 改完 app.py 后重启
docker compose down               # 停止（保留数据）
docker compose down -v            # 停止并删除数据库和模型 ⚠️
```

改了 `schema.sql` 之后必须 `down -v` 再起，因为初始化脚本只在数据目录为空时执行一次。

## 性能预期

qwen3:4b 在纯 CPU 上，一次回答大概十几秒到半分钟。所以：
- nginx 和 gunicorn 的超时都调到了 300 秒，避免 504；
- 前端加载提示写了"本地模型，首次回答可能要等十几秒"；
- 如果嫌慢，要么上 GPU，要么后面加流式输出让用户看到字在往外蹦。
