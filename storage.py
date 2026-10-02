"""Состояния пользователей и заявки в SQLite, без внешнего сервера."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class Store:
    def __init__(self, path=None):
        self.path = str(path or Path(__file__).with_name("shop.sqlite3"))
        self.db = sqlite3.connect(self.path)
        self.db.execute("CREATE TABLE IF NOT EXISTS sessions (user_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
            created_at TEXT NOT NULL, data TEXT NOT NULL)""")
        self.db.commit()

    def load(self, user_id):
        row = self.db.execute("SELECT data FROM sessions WHERE user_id=?", (str(user_id),)).fetchone()
        return json.loads(row[0]) if row else {"stage": None, "criteria": {}, "shown": [], "cart": [], "draft": {}}

    def save(self, user_id, state):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?)", (str(user_id), json.dumps(state, ensure_ascii=False)))

    def place_order(self, user_id, state, order):
        # Запись заявки и очистка корзины выполняются одной транзакцией.
        with self.db:
            cursor = self.db.execute("INSERT INTO orders (user_id,created_at,data) VALUES (?,?,?)", (
                str(user_id), datetime.now(timezone.utc).isoformat(), json.dumps(order, ensure_ascii=False)))
            self.db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?)", (str(user_id), json.dumps(state, ensure_ascii=False)))
        return cursor.lastrowid

    def orders(self, user_id):
        rows = self.db.execute("SELECT id,created_at,data FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (str(user_id),)).fetchall()
        return [(i, date, json.loads(data)) for i, date, data in rows]

    def close(self):
        self.db.close()
