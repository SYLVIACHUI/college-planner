FROM python:3.11-slim

WORKDIR /app

# 先单独装依赖，改代码时可以复用这层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 5000

# 本地模型响应慢，worker 超时给到 300 秒，
# 2 个 worker 足够（真正的瓶颈在 Ollama 那边，不在 Flask）
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "--timeout", "300", "app:app"]
