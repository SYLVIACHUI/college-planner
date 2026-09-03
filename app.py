"""
大学生日程表 AI Agent - 后端服务
技术栈：Flask + PyMySQL + Ollama（本地大模型，默认 qwen3:4b）

AI 部分走本地 Ollama，不需要任何云端 API key。
权限/登录先用简单的 user_id 参数代替，
后续接入真正的登录态时，把 get_user_id() 换成从 session/JWT 里取即可。
"""
import os
import re
import json
from datetime import datetime

import pymysql
import pymysql.cursors
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

DB_CONFIG = dict(
    host=os.getenv("DB_HOST", "127.0.0.1"),
    port=int(os.getenv("DB_PORT", "3306")),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", ""),
    database=os.getenv("DB_NAME", "student_planner"),
    charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
)

# Ollama 配置。docker-compose 里 OLLAMA_HOST 会被设成 http://ollama:11434
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
# 本地模型比云端慢不少，超时给宽松一点（秒）
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "180"))


def get_db():
    return pymysql.connect(**DB_CONFIG)


def get_user_id():
    """演示阶段：从 query/body 里读 user_id，默认 1。接入登录后替换成真实用户态。"""
    return int(request.values.get("user_id", 1))


# ---------------------------------------------------------------------------
# 类别
# ---------------------------------------------------------------------------
@app.get("/api/categories")
def list_categories():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT `key`, name, color, bg_color, emoji FROM categories ORDER BY sort_order")
            return jsonify(cur.fetchall())


# ---------------------------------------------------------------------------
# 日程块
# ---------------------------------------------------------------------------
@app.get("/api/blocks")
def list_blocks():
    user_id = get_user_id()
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT b.id, b.day_of_week, b.hour, b.title, b.notes,
                       c.`key` AS category_key, c.name AS category_name,
                       c.color, c.bg_color, c.emoji
                FROM schedule_blocks b
                JOIN categories c ON c.id = b.category_id
                WHERE b.user_id = %s
                """,
                (user_id,),
            )
            return jsonify(cur.fetchall())


@app.post("/api/blocks")
def create_block():
    """把一个日程块拖入表格：新增一条记录（同一格子已存在则覆盖）。"""
    data = request.get_json(force=True)
    user_id = get_user_id()
    day_of_week = int(data["day_of_week"])   # 1-7
    hour = int(data["hour"])                 # 0-23
    category_key = data["category_key"]
    title = data.get("title") or ""
    notes = data.get("notes") or ""

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM categories WHERE `key` = %s", (category_key,))
            cat = cur.fetchone()
            if not cat:
                return jsonify({"error": "未知的日程类别"}), 400

            title = title or cat["name"]

            cur.execute(
                """
                INSERT INTO schedule_blocks (user_id, category_id, day_of_week, hour, title, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  category_id = VALUES(category_id),
                  title = VALUES(title),
                  notes = VALUES(notes)
                """,
                (user_id, cat["id"], day_of_week, hour, title, notes),
            )
            conn.commit()
            cur.execute(
                "SELECT id FROM schedule_blocks WHERE user_id=%s AND day_of_week=%s AND hour=%s",
                (user_id, day_of_week, hour),
            )
            return jsonify(cur.fetchone()), 201


@app.put("/api/blocks/<int:block_id>")
def update_block(block_id):
    """修改标题/备注，或者拖动到新的格子（传新的 day_of_week / hour）。"""
    data = request.get_json(force=True)
    user_id = get_user_id()
    fields, values = [], []

    for col in ("title", "notes", "day_of_week", "hour"):
        if col in data:
            fields.append(f"{col} = %s")
            values.append(data[col])

    if not fields:
        return jsonify({"error": "没有需要更新的字段"}), 400

    values += [block_id, user_id]
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE schedule_blocks SET {', '.join(fields)} WHERE id=%s AND user_id=%s",
                values,
            )
            conn.commit()
            return jsonify({"updated": cur.rowcount > 0})


@app.delete("/api/blocks/<int:block_id>")
def delete_block(block_id):
    user_id = get_user_id()
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM schedule_blocks WHERE id=%s AND user_id=%s", (block_id, user_id))
            conn.commit()
            return jsonify({"deleted": cur.rowcount > 0})


# ---------------------------------------------------------------------------
# AI 分析
# ---------------------------------------------------------------------------
DAY_NAMES = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 对话轮数上限：只把最近 N 条历史发给模型，避免 token 无限增长
MAX_HISTORY_MESSAGES = 20


def load_blocks(user_id):
    """从数据库读该用户的全部日程块。"""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT b.day_of_week, b.hour, b.title, b.notes, c.name AS category_name
                FROM schedule_blocks b JOIN categories c ON c.id = b.category_id
                WHERE b.user_id = %s
                ORDER BY b.day_of_week, b.hour
                """,
                (user_id,),
            )
            return cur.fetchall()


def normalize_blocks(raw):
    """
    兼容前端直接传过来的日程快照。
    目前 index.html 的数据还存在浏览器内存里（没有走 /api/blocks），
    所以允许前端把当前表格内容随请求一起发上来；等前端接了 CRUD 接口后，
    这里传 None，后端就自己从数据库读。
    """
    if not raw:
        return []
    out = []
    for b in raw:
        try:
            day = int(b.get("day_of_week"))
            hour = int(b.get("hour"))
        except (TypeError, ValueError):
            continue
        if not (1 <= day <= 7 and 0 <= hour <= 23):
            continue
        out.append({
            "day_of_week": day,
            "hour": hour,
            "title": (b.get("title") or "").strip()[:64],
            "notes": (b.get("notes") or "").strip()[:500],
            "category_name": (b.get("category_name") or "其他").strip()[:32],
        })
    out.sort(key=lambda x: (x["day_of_week"], x["hour"]))
    return out


def resolve_blocks(data, user_id):
    """请求里带了 blocks 就用它，否则回落到数据库。"""
    if isinstance(data, dict) and "blocks" in data:
        return normalize_blocks(data.get("blocks"))
    return load_blocks(user_id)


def format_schedule(blocks):
    """把日程块拼成给模型看的纯文本，分析和聊天共用。"""
    if not blocks:
        return "（用户目前还没有往日程表里放任何日程块。）"

    lines, tally = [], {}
    for b in blocks:
        note_part = f"，备注：{b['notes'].strip()}" if b.get("notes") and b["notes"].strip() else ""
        lines.append(f"{DAY_NAMES[b['day_of_week']]} {b['hour']}:00 【{b['category_name']}】{b['title']}{note_part}")
        tally[b["category_name"]] = tally.get(b["category_name"], 0) + 1

    hours_summary = "，".join(f"{name} {h} 小时" for name, h in tally.items())
    return "\n".join(lines) + f"\n\n各类别本周合计时长：{hours_summary}"


THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
DANGLING_THINK_RE = re.compile(r"^.*?</think>", re.DOTALL | re.IGNORECASE)


def strip_thinking(text):
    """
    qwen3 是混合推理模型，默认会先输出一段 <think>...</think> 的思考过程。
    这段是给模型自己用的，不能直接显示给用户，这里统一剥掉。
    即使请求里已经关了 think，也保留这层兜底 —— 不同版本行为不完全一致。
    """
    text = THINK_TAG_RE.sub("", text)
    # 处理只有结束标签的情况（思考被截断，或开始标签没吐出来）
    if "</think>" in text:
        text = DANGLING_THINK_RE.sub("", text)
    # 处理只有开始标签、没有结束标签的情况（生成被 num_predict 截断）
    if "<think>" in text:
        text = text.split("<think>")[0]
    return text.strip()


def call_llm(system, messages, max_tokens=800):
    """
    调用本地 Ollama 的 /api/chat，返回纯文本。
    失败时抛异常，由各接口自己处理。
    """
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "system", "content": system}] + messages,
        "stream": False,
        # 关掉 qwen3 的思考模式：本地小模型思考起来很慢，而且这个场景不需要长推理
        "think": False,
        "options": {
            "temperature": 0.7,
            "num_predict": max_tokens,
        },
    }

    resp = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=OLLAMA_TIMEOUT)

    # 老版本 Ollama 不认识 think 字段，去掉重试一次
    if resp.status_code == 400 and "think" in payload:
        payload.pop("think")
        resp = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=OLLAMA_TIMEOUT)

    if resp.status_code == 404:
        raise RuntimeError(f"Ollama 里没有找到模型 {OLLAMA_MODEL}，先执行 ollama pull {OLLAMA_MODEL}")
    resp.raise_for_status()

    data = resp.json()
    content = (data.get("message") or {}).get("content", "")
    return strip_thinking(content)


def build_prompt(blocks):
    lines = []
    tally = {}
    for b in blocks:
        note_part = f"，备注：{b['notes'].strip()}" if b.get("notes") and b["notes"].strip() else ""
        lines.append(f"{DAY_NAMES[b['day_of_week']]} {b['hour']}:00 【{b['category_name']}】{b['title']}{note_part}")
        tally[b["category_name"]] = tally.get(b["category_name"], 0) + 1

    hours_summary = "，".join(f"{name} {h} 小时" for name, h in tally.items())

    return f"""这是一名大学生本周的日程安排（按类别分组，格式为"星期 时间 【类别】标题，备注"）：

{chr(10).join(lines)}

各类别本周合计时长：{hours_summary or '暂无记录'}

请你作为学习与时间管理助手，基于以上安排和备注内容，用简洁的中文给出：
1. 时间分配上的观察（是否有明显失衡，比如学习/休息/健身占比）；
2. 从备注内容里能看出的具体情况或潜在问题（如果备注信息很少，就如实说明，不要编造）；
3. 2-3条具体、可执行的调整建议。
不要使用markdown标题符号，用简短的自然段或编号列表即可，总字数控制在300字以内。"""


@app.post("/api/ai/analyze")
def ai_analyze():
    user_id = get_user_id()
    data = request.get_json(silent=True) or {}
    blocks = resolve_blocks(data, user_id)

    if not blocks:
        return jsonify({"result": "日程表还是空的，先放几个日程块进去再分析吧。"})

    prompt = build_prompt(blocks)

    try:
        result_text = call_llm(
            "你是一个细心、诚实的大学生时间管理助手。只依据用户提供的日程和备注做分析，不要编造用户没写的信息。",
            [{"role": "user", "content": prompt}],
        )
    except Exception as e:
        return jsonify({"error": f"AI 分析失败：{e}"}), 502

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ai_analyses (user_id, input_summary, result) VALUES (%s, %s, %s)",
                (user_id, prompt, result_text),
            )
            conn.commit()

    return jsonify({"result": result_text})


# ---------------------------------------------------------------------------
# AI 对话问答
# ---------------------------------------------------------------------------
CHAT_SYSTEM = """你是一个大学生的日程与学习助手，说话简洁、务实、有点温度，用中文回答。

你可以看到用户当前这一周的日程表内容（下面会给出）。回答时：
- 涉及用户具体安排的问题，必须以日程表里的真实内容为准，不要编造用户没写过的课程、备注或时间；
- 日程表里没有的信息，就直说"你的表里没有记录这个"，然后再给通用建议；
- 用户问的是与日程无关的普通问题（学习方法、考试、生活等），正常回答即可，不用硬扯回日程；
- 不要用 markdown 标题符号，回答控制在 200 字以内，除非用户明确要求展开。

当前用户的日程表：
{schedule}"""


def save_chat_messages(user_id, session_id, pairs):
    """pairs: [(role, content), ...]"""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO ai_chat_messages (user_id, session_id, role, content) VALUES (%s, %s, %s, %s)",
                [(user_id, session_id, role, content) for role, content in pairs],
            )
            conn.commit()


@app.post("/api/ai/chat")
def ai_chat():
    """
    请求体：
      {
        "message": "我周三是不是排太满了？",
        "session_id": "默认 default",
        "history": [{"role":"user","content":"..."}, {"role":"assistant","content":"..."}],
        "blocks": [ ...可选，前端当前表格快照... ]
      }
    返回：{"reply": "..."}
    """
    user_id = get_user_id()
    data = request.get_json(force=True, silent=True) or {}

    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "问题不能为空"}), 400
    if len(message) > 2000:
        return jsonify({"error": "问题太长了，麻烦精简一下"}), 400

    session_id = (data.get("session_id") or "default")[:64]

    # 历史对话：优先用前端传的（省一次查询），没传就从数据库读
    history = data.get("history")
    if history is None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT role, content FROM ai_chat_messages
                    WHERE user_id=%s AND session_id=%s
                    ORDER BY id DESC LIMIT %s
                    """,
                    (user_id, session_id, MAX_HISTORY_MESSAGES),
                )
                history = list(reversed(cur.fetchall()))

    messages = []
    for h in (history or [])[-MAX_HISTORY_MESSAGES:]:
        role = h.get("role")
        content = (h.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    # Anthropic 要求首条必须是 user，历史被截断时可能不满足
    while messages and messages[0]["role"] != "user":
        messages.pop(0)

    messages.append({"role": "user", "content": message})

    schedule_text = format_schedule(resolve_blocks(data, user_id))
    system = CHAT_SYSTEM.format(schedule=schedule_text)

    try:
        reply = call_llm(system, messages, max_tokens=800)
    except Exception as e:
        return jsonify({"error": f"AI 回复失败：{e}"}), 502

    if not reply:
        reply = "我这边没有生成出有效回复，换个说法再问一次试试？"

    try:
        save_chat_messages(user_id, session_id, [("user", message), ("assistant", reply)])
    except Exception as e:
        # 存历史失败不该影响用户拿到回答
        app.logger.warning("保存对话记录失败：%s", e)

    return jsonify({"reply": reply})


@app.get("/api/ai/chat/history")
def ai_chat_history():
    user_id = get_user_id()
    session_id = request.args.get("session_id", "default")[:64]
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, content, created_at FROM ai_chat_messages
                WHERE user_id=%s AND session_id=%s ORDER BY id
                """,
                (user_id, session_id),
            )
            rows = cur.fetchall()
    for r in rows:
        r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(rows)


@app.delete("/api/ai/chat/history")
def ai_chat_clear():
    user_id = get_user_id()
    session_id = request.values.get("session_id", "default")[:64]
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM ai_chat_messages WHERE user_id=%s AND session_id=%s",
                (user_id, session_id),
            )
            conn.commit()
            return jsonify({"deleted": cur.rowcount})


# ---------------------------------------------------------------------------
# 健康检查：确认数据库和 Ollama 都就绪
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    status = {"db": False, "ollama": False, "model": OLLAMA_MODEL, "model_ready": False}

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        status["db"] = True
    except Exception as e:
        status["db_error"] = str(e)

    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
        status["ollama"] = True
        status["available_models"] = names
        # ollama 里模型名可能带 :latest 后缀，两边都比一下
        status["model_ready"] = any(
            n == OLLAMA_MODEL or n.split(":")[0] == OLLAMA_MODEL.split(":")[0]
            for n in names
        )
    except Exception as e:
        status["ollama_error"] = str(e)

    ok = status["db"] and status["ollama"] and status["model_ready"]
    return jsonify(status), (200 if ok else 503)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
