-- 大学生日程表 AI Agent - 数据库结构
-- 字符集使用 utf8mb4 以完整支持中文与表情符号

CREATE DATABASE IF NOT EXISTS student_planner
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE student_planner;

-- 用户表（先做单用户/演示账号也可以，字段留好方便以后扩展多用户）
CREATE TABLE IF NOT EXISTS users (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  username      VARCHAR(64) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- 演示账号：后端目前用固定 user_id=1，没有这条记录的话
-- schedule_blocks / ai_analyses / ai_chat_messages 的外键会直接插入失败
INSERT INTO users (id, username, password_hash) VALUES (1, 'demo', 'demo-not-a-real-hash')
ON DUPLICATE KEY UPDATE username = VALUES(username);

-- 日程类别（学习/健身/作业...），颜色和图标由前端渲染用
CREATE TABLE IF NOT EXISTS categories (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  `key`      VARCHAR(32) NOT NULL UNIQUE,   -- study / fitness / work ...
  name       VARCHAR(32) NOT NULL,          -- 学习 / 健身 / 作业 ...
  color      VARCHAR(16) NOT NULL,          -- 主题色 hex
  bg_color   VARCHAR(16) NOT NULL,          -- 浅底色 hex
  emoji      VARCHAR(8)  DEFAULT NULL,
  sort_order INT NOT NULL DEFAULT 0
) ENGINE=InnoDB;

INSERT INTO categories (`key`, name, color, bg_color, emoji, sort_order) VALUES
  ('study',   '学习', '#3E6CE0', '#E7ECFB', '📚', 1),
  ('fitness', '健身', '#E0762F', '#FBEBDF', '🏃', 2),
  ('work',    '作业', '#2F8F72', '#E1F1EB', '📝', 3),
  ('social',  '社交', '#C24A72', '#F7E4EC', '👥', 4),
  ('fun',     '娱乐', '#C79A21', '#F7EFD8', '🎮', 5),
  ('rest',    '休息', '#6E6A8C', '#EBEAF3', '🛌', 6),
  ('other',   '其他', '#7A5AC0', '#EEE8FA', '✨', 7)
ON DUPLICATE KEY UPDATE name = VALUES(name);

-- 放入周视图表格中的日程块
CREATE TABLE IF NOT EXISTS schedule_blocks (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  user_id     INT NOT NULL,
  category_id INT NOT NULL,
  day_of_week TINYINT NOT NULL,   -- 1=周一 ... 7=周日
  hour        TINYINT NOT NULL,   -- 0-23
  title       VARCHAR(64) NOT NULL,
  notes       TEXT,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (category_id) REFERENCES categories(id),
  UNIQUE KEY uniq_slot (user_id, day_of_week, hour)  -- 每人每个时间格只能放一个日程块
) ENGINE=InnoDB;

-- 记录每次 AI 分析结果，方便用户回顾历史建议
CREATE TABLE IF NOT EXISTS ai_analyses (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  user_id    INT NOT NULL,
  input_summary TEXT,     -- 发给模型的日程摘要（便于复现/调试）
  result     TEXT,        -- 模型返回的分析内容
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 多轮对话消息（AI 助手问答）
-- 一次会话用 session_id 串起来，前端每次刷新可以生成一个新的 session_id，
-- 也可以固定成一个值，让用户下次打开还能看到之前的对话。
CREATE TABLE IF NOT EXISTS ai_chat_messages (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  user_id    INT NOT NULL,
  session_id VARCHAR(64) NOT NULL DEFAULT 'default',
  role       ENUM('user','assistant') NOT NULL,
  content    TEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  KEY idx_session (user_id, session_id, id)
) ENGINE=InnoDB;
