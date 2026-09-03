"""
大学生日程表 AI Agent - 后端服务
技术栈：Flask + PyMySQL + Anthropic API

先跑通接口逻辑，权限/登录先用简单的 user_id 参数代替，
后续接入真正的登录态时，把 get_user_id() 换成从 session/JWT 里取即可。
"""
import os
import json
from datetime import datetime

import pymysql
import pymysql.cursors
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

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")


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
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "服务端未配置 ANTHROPIC_API_KEY"}), 500

    user_id = get_user_id()
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
            blocks = cur.fetchall()

    if not blocks:
        return jsonify({"result": "日程表还是空的，先放几个日程块进去再分析吧。"})

    prompt = build_prompt(blocks)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1000,
            system="你是一个细心、诚实的大学生时间管理助手。只依据用户提供的日程和备注做分析，不要编造用户没写的信息。",
            messages=[{"role": "user", "content": prompt}],
        )
        result_text = "".join(block.text for block in resp.content if block.type == "text").strip()
    except Exception as e:
        return jsonify({"error": f"AI 分析请求失败：{e}"}), 502

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ai_analyses (user_id, input_summary, result) VALUES (%s, %s, %s)",
                (user_id, prompt, result_text),
            )
            conn.commit()

    return jsonify({"result": result_text})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
