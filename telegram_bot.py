"""Telegram long polling через официальный Bot API и стандартную библиотеку.

Не требует python-telegram-bot или python-dotenv. Токен берётся из окружения
или .env рядом с файлом. Сообщения обрабатываются последовательно.
"""
import json
import logging
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from main import ShopBot
from storage import Store

LOG = logging.getLogger("coatbot")
KEYBOARD = {"keyboard": [
    ["Подобрать одежду", "Каталог"], ["Корзина", "Оформить заказ"],
    ["Мои заказы", "Помощь"], ["Начать заново", "Отмена"],
], "resize_keyboard": True, "is_persistent": True}


def load_env(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key in ("TELEGRAM_TOKEN", "BOT_DB_PATH"):
            os.environ.setdefault(key, value.strip("\"'"))


class TelegramError(Exception):
    def __init__(self, code, retry_after=None):
        self.code = code
        self.retry_after = retry_after
        # Не сохраняем URL запроса, содержащий токен, в тексте ошибки.
        super().__init__(f"Ошибка Telegram API: {code}")


class TelegramClient:
    def __init__(self, token):
        self.base_url = f"https://api.telegram.org/bot{token}/"

    def call(self, method, **params):
        request = Request(self.base_url + method, data=json.dumps(params).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=40) as response:
                payload = json.loads(response.read())
        except HTTPError as error:
            try:
                payload = json.loads(error.read())
            except (ValueError, OSError):
                raise TelegramError(error.code) from None
        except (URLError, TimeoutError, OSError):
            raise TelegramError("network") from None
        if not payload.get("ok"):
            raise TelegramError(payload.get("error_code", "unknown"), payload.get("parameters", {}).get("retry_after"))
        return payload["result"]

    def send(self, chat_id, text):
        # Длинные каталоги и корзины разбиваются на отдельные сообщения.
        for chunk in split_message(text):
            self.call("sendMessage", chat_id=chat_id, text=chunk, reply_markup=KEYBOARD)


def split_message(text, limit=3500):
    while len(text) > limit:
        end = text.rfind("\n", 0, limit)
        if end < limit // 2:
            end = limit
        yield text[:end]
        text = text[end:].lstrip("\n")
    if text:
        yield text


def handle_update(engine, update):
    message = update.get("message")
    if not message or message.get("chat", {}).get("type") != "private":
        return None
    sender = message.get("from", {})
    if not sender.get("id") or sender.get("is_bot"):
        return None
    chat_id = message["chat"]["id"]
    text = message.get("text")
    if not text:
        return chat_id, "Пока я принимаю только текст. Выберите кнопку или напишите запрос."
    return chat_id, engine.reply(text, user_id=sender["id"])


def run(client, engine):
    # offset хранится отдельно от пользовательского состояния и переживает перезапуск.
    cursor = engine.store.load("__telegram_offset__")
    offset = cursor.get("offset", 0)
    while True:
        try:
            updates = client.call("getUpdates", offset=offset, timeout=25, allowed_updates=["message"])
            for update in updates:
                result = handle_update(engine, update)
                offset = update["update_id"] + 1
                engine.store.save("__telegram_offset__", {"offset": offset})
                if result:
                    try:
                        client.send(*result)
                    except TelegramError as error:
                        if error.code in (401, 404, 409):
                            raise
                        if error.retry_after:
                            time.sleep(min(error.retry_after, 30))
                            client.send(*result)
                        else:
                            LOG.warning("Не удалось отправить ответ (%s). Данные диалога сохранены.", error.code)
        except TelegramError as error:
            if error.code in (401, 404):
                LOG.error("Токен неверен или отозван. Проверьте TELEGRAM_TOKEN.")
                return 1
            if error.code == 409:
                LOG.error("Конфликт получения обновлений. Остановите второй экземпляр бота и проверьте webhook.")
                return 1
            LOG.warning("Связь с Telegram недоступна (%s), повторяем запрос.", error.code)
            time.sleep(min(error.retry_after or 5, 30))


def main():
    load_env(Path(__file__).with_name(".env"))
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        print("Токен не задан. Запустите setup_token.py в PyCharm и сохраните токен вашего бота.")
        return 1
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    client = TelegramClient(token)
    try:
        me = client.call("getMe")
        webhook = client.call("getWebhookInfo")
        if webhook.get("url"):
            print("Для этого токена настроен webhook. Удалите webhook перед запуском режима polling.")
            return 1
    except TelegramError as error:
        print(f"Не удалось подключиться к Telegram ({error.code}). Проверьте токен и интернет.")
        return 1
    db_path = os.getenv("BOT_DB_PATH") or None
    engine = ShopBot(Store(db_path))
    print(f"CoatBot запущен: @{me.get('username', 'bot')}. Для остановки Ctrl+C.")
    try:
        return run(client, engine)
    except KeyboardInterrupt:
        print("\nБот остановлен.")
        return 0
    finally:
        engine.store.close()


if __name__ == "__main__":
    raise SystemExit(main())
