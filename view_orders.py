"""Просмотр сохранённых заявок продавцом на своём компьютере."""
import argparse
import json
import sqlite3
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Посмотреть учебные заявки CoatBot")
    parser.add_argument("--db", type=Path, default=Path(__file__).with_name("shop.sqlite3"))
    args = parser.parse_args()
    if not args.db.is_file():
        print("База ещё не создана. Сначала запустите бота и оформите заявку.")
        return
    db = sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = db.execute("SELECT id,user_id,created_at,data FROM orders ORDER BY id DESC").fetchall()
        if not rows:
            print("Заявок пока нет.")
        for number, user_id, date, content in rows:
            order = json.loads(content)
            print(f"\nЗаявка №{number} от {date} · пользователь {user_id}")
            print(f"{order['name']} · {order['phone']} · {order['city']}")
            for item in order["items"]:
                print(f"  {item['name']} ({item['id']}) · размер {item['size']} · {item['quantity']} шт. · {item['price']} ₽ за шт.")
            print(f"Итого: {order['total']} ₽ · {order['status']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
