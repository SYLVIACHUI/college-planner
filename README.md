# 大学生日程表 AI Agent · 第一版

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
  （这一步会真实调用 Anthropic API，所以需要联网；分析内容完全基于你已填写的备注，不会编造）

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
