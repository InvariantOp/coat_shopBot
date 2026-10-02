"""Проверки сценариев без токена и запросов к Telegram."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from io import BytesIO

from main import ShopBot, parse_criteria, edit_distance, load_dialogues, order_date, HELP
from bot_config import BOT_CONFIG
from setup_token import save_token
from products import find_products
from storage import Store
from telegram_bot import TelegramClient, TelegramError, handle_update, split_message, run


class BotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ShopBot(Store(":memory:"))

    @classmethod
    def tearDownClass(cls):
        cls.engine.store.close()

    def setUp(self):
        self.user = self.id()

    def say(self, text):
        return self.engine.reply(text, self.user)

    def state(self):
        return self.engine.store.load(self.user)

    def test_wizard(self):
        for text, stage in [("Подобрать одежду", "category"), ("куртка", "season"),
                            ("демисезон", "size"), ("46", "budget"), ("6000", "choose")]:
            self.say(text)
            self.assertEqual(self.state()["stage"], stage)
        self.assertEqual(self.state()["shown"], ["J01"])
        self.say("1")
        self.assertEqual(self.state()["cart"], [{"id": "J01", "size": 46, "quantity": 1}])

    def test_direct_request(self):
        self.say("женский зимний пуховик размер 46 до 10000")
        self.assertEqual(self.state()["shown"], ["D01"])
        self.say("купить D01")
        self.assertEqual(self.state()["cart"][0]["size"], 46)

    def test_no_matches_do_not_relax_filters(self):
        answer = self.say("пальто размер 56 до 1000")
        self.assertIn("моделей нет", answer)
        self.assertEqual(self.state()["shown"], [])
        self.assertEqual(self.state()["criteria"]["budget"], 1000)

    def test_size_validation_and_quantity(self):
        self.say("купить J01")
        self.assertEqual(self.state()["stage"], "product_size")
        self.say("99")
        self.assertFalse(self.state()["cart"])
        self.say("46")
        self.say("добавить J01 46")
        self.assertEqual(self.state()["cart"][0]["quantity"], 2)
        self.assertIn("9980", self.say("Корзина"))

    def test_multiple_users(self):
        other = self.user + "_other"
        self.say("Подобрать одежду")
        self.engine.reply("купить D01 44", other)
        self.assertEqual(self.state()["stage"], "category")
        self.assertFalse(self.state()["cart"])
        self.assertEqual(self.engine.store.load(other)["cart"][0]["id"], "D01")

    def test_cancel_and_reset_preserve_cart(self):
        self.say("добавить J01 46")
        self.say("Оформить заказ")
        self.say("Анна")
        self.say("Отмена")
        self.assertEqual(self.state()["draft"], {})
        self.assertEqual(len(self.state()["cart"]), 1)
        self.say("/reset")
        self.assertEqual(len(self.state()["cart"]), 1)

    def test_checkout_validation_and_order_isolation(self):
        self.say("добавить J01 46")
        self.say("Оформить заказ")
        self.say("Анна")
        self.say("123")
        self.assertEqual(self.state()["stage"], "phone")
        self.say("+7 (999) 123-45-67")
        self.say("Москва")
        self.assertEqual(self.state()["stage"], "confirm")
        self.assertFalse(self.engine.store.orders(self.user))
        self.assertIn("оформлен", self.say("Да"))
        orders = self.engine.store.orders(self.user)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0][2]["total"], 4990)
        self.assertEqual(orders[0][2]["phone"], "+79991234567")
        self.assertEqual(self.state()["cart"], [])
        self.say("Да")
        self.assertEqual(len(self.engine.store.orders(self.user)), 1)
        self.assertFalse(self.engine.store.orders(self.user + "_other"))

    def test_declining_checkout(self):
        for text in ["добавить R01 44", "Оформить заказ", "Анна", "79991234567", "Москва", "Нет"]:
            self.say(text)
        self.assertIsNone(self.state()["stage"])
        self.assertEqual(len(self.state()["cart"]), 1)
        self.assertFalse(self.engine.store.orders(self.user))

    def test_cart_delete_and_clear(self):
        self.say("добавить J01 46")
        self.say("добавить D01 44")
        self.say("Удалить 0")
        self.assertEqual(len(self.state()["cart"]), 2)
        self.say("Удалить 1")
        self.assertEqual(self.state()["cart"][0]["id"], "D01")
        self.say("Очистить корзину")
        self.assertFalse(self.state()["cart"])

    def test_info_question_during_selection(self):
        self.say("Подобрать одежду")
        self.assertIn("достав", self.say("доставка"))
        self.assertEqual(self.state()["stage"], "category")

    def test_skip_all_filters(self):
        for text in ["Подобрать одежду", "любая категория", "любой сезон", "любой размер", "без ограничения"]:
            self.say(text)
        self.assertEqual(len(self.state()["shown"]), 10)

    def test_budget_parsing(self):
        for text in ["куртка 46 до 5000", "куртка 46 до 5 000", "куртка 46 до 5 тыс", "куртка 46 бюджет 5к"]:
            self.assertEqual(parse_criteria(text)["budget"], 5000)

    def test_intent_model_and_unknown(self):
        self.assertIn("CoatBot", self.say("привет"))
        self.assertIn("CoatBot", self.say("как тебя зовут"))
        self.assertIn("Не удалось понять", self.say("абракадабра квазикристалл"))
        self.assertIn("Цена", self.say("какие цены"))

    def test_budget_is_not_size(self):
        self.assertEqual(parse_criteria("пальто до 50 тыс"), {"category": "coats", "budget": 50000})

    def test_ambiguous_codes_preserve_selection(self):
        self.say("Каталог")
        state = self.state()
        self.assertIn("Выберите одну", self.say("D02 купить J01"))
        self.assertEqual(self.state(), state)

    def test_bare_code_and_reverse_buy(self):
        self.say("D02")
        self.assertEqual(self.state()["selected"], "D02")
        self.say("J01 купить")
        self.assertEqual(self.state()["selected"], "J01")

    def test_moscow_order_date(self):
        self.assertEqual(order_date("2026-09-30T22:58:00+00:00"), "01.10.2026")

    def test_checkout_text_has_no_demo_notices(self):
        self.assertNotIn("учебный", self.say("Каталог"))
        self.assertNotIn("учебный", HELP)
        self.say("купить J01 46")
        messages = [self.say(x) for x in ["Оформить заказ", "Анна", "79991234567", "Москва", "Да"]]
        for message in messages:
            for word in ["учебн", "демонстрац", "списыва", "без оплаты"]:
                self.assertNotIn(word, message.lower())
        self.assertIn("без оплаты", self.say("Мои заказы"))

    def test_main_button_interrupts_checkout(self):
        self.say("купить J01 46")
        self.say("Оформить заказ")
        self.say("Подобрать одежду")
        self.assertEqual(self.state()["stage"], "category")
        self.assertEqual(self.state()["draft"], {})

    def test_invalid_budget(self):
        for text in ["Подобрать одежду", "куртка", "демисезон", "46"]:
            self.say(text)
        self.say("0")
        self.assertEqual(self.state()["stage"], "budget")
        self.say("-1000")
        self.assertEqual(self.state()["stage"], "budget")

    def test_database_survives_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shop.sqlite3"
            first = Store(path)
            first.save("a", {"stage": "phone", "cart": [{"id": "J01"}]})
            first.close()
            second = Store(path)
            self.assertEqual(second.load("a")["stage"], "phone")
            self.assertEqual(second.load("a")["cart"][0]["id"], "J01")
            self.assertFalse(second.load("b")["cart"])
            second.close()

    def test_ad_requires_consent(self):
        answer = self.say("мне холодно")
        self.assertIn("Хотите", answer)
        self.assertEqual(self.state()["stage"], "ad_offer")
        self.assertEqual(self.state()["shown"], [])
        self.say("Да")
        self.assertEqual(self.state()["stage"], "size")
        self.say("46")
        self.say("10000")
        self.assertEqual(self.state()["shown"], ["D01"])

    def test_decline_ad_and_keep_chatting(self):
        self.say("идет дождь")
        self.say("Нет")
        self.assertIsNone(self.state()["stage"])
        self.assertFalse(self.state()["shown"])
        self.assertNotIn("Хотите", self.say("скоро зима"))
        self.assertIsNone(self.state()["stage"])
        self.assertIn("Что", self.say("читаю книгу"))

    def test_topic_change_during_ad_offer(self):
        self.say("скоро зима")
        self.assertIn("Музыка", self.say("люблю музыку"))
        self.assertIsNone(self.state()["stage"])

    def test_ads_can_be_disabled_and_reset(self):
        self.say("без рекламы")
        self.say("мне холодно")
        self.assertFalse(self.state()["shown"])
        self.assertIsNone(self.state()["stage"])
        self.say("/reset")
        self.say("мне холодно")
        self.assertEqual(self.state()["stage"], "ad_offer")

    def test_walking_not_confused_with_product(self):
        self.assertNotIn("category", parse_criteria("гуляю в парке"))
        self.say("гуляю в парке")
        self.assertEqual(self.state()["stage"], "ad_offer")
        self.assertEqual(self.state()["offer"]["category"], "parkas")

    def test_direct_request_bypasses_ad(self):
        self.say("нужен зимний пуховик размер 46 до 10000")
        self.assertEqual(self.state()["stage"], "choose")
        self.assertEqual(self.state()["shown"], ["D01"])

    def test_expanded_datasets_and_typo(self):
        dialogues = load_dialogues()
        self.assertGreaterEqual(len(dialogues), 60)
        self.assertEqual(len(dialogues), len({q for q,a in dialogues}))
        self.assertGreaterEqual(len(BOT_CONFIG["intents"]), 20)
        self.assertGreaterEqual(sum(len(x["examples"]) for x in BOT_CONFIG["intents"].values()), 150)
        self.assertEqual(edit_distance("привет", "превет"), 1)
        self.assertIn("Книги", self.say("люблю читат"))

    def test_information_questions_are_not_purchase_requests(self):
        self.assertIn("переходные сезоны", self.say("что такое демисезон"))
        self.assertIsNone(self.state()["stage"])
        self.assertIn("обычно длиннее", self.say("чем отличается парка от куртки"))

    def test_chat_during_selection_preserves_stage(self):
        self.say("Подобрать одежду")
        self.say("куртка")
        self.assertIn("курсовой", self.say("делаю курсовую"))
        self.assertEqual(self.state()["stage"], "season")

    def test_ad_state_is_independent_per_user(self):
        self.say("мне холодно")
        other = self.user + "_other"
        self.engine.reply("идет дождь", other)
        self.assertEqual(self.state()["offer"]["category"], "down")
        self.assertEqual(self.engine.store.load(other)["offer"]["category"], "raincoats")


class ConfigurationTests(unittest.TestCase):
    def test_save_and_update_token_preserves_database_path(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text("TELEGRAM_TOKEN = old\nBOT_DB_PATH=custom.sqlite3\n", encoding="utf-8")
            token = "123456789:" + "A" * 35
            save_token(token, path)
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("TELEGRAM_TOKEN"), 1)
            self.assertIn("BOT_DB_PATH=custom.sqlite3", text)
            self.assertIn(token, text)

    def test_invalid_token_is_not_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            with self.assertRaises(ValueError):
                save_token("not-a-token", path)
            self.assertFalse(path.exists())


class TelegramTests(unittest.TestCase):
    def setUp(self):
        self.engine = ShopBot(Store(":memory:"))

    def tearDown(self):
        self.engine.store.close()

    def test_private_chat_update(self):
        update = {"update_id": 1, "message": {"chat": {"id": 42, "type": "private"}, "from": {"id": 42}, "text": "купить J01 46"}}
        chat, answer = handle_update(self.engine, update)
        self.assertEqual(chat, 42)
        self.assertIn("Добавлено", answer)
        self.assertEqual(self.engine.store.load(42)["cart"][0]["id"], "J01")
        update["message"]["chat"]["type"] = "group"
        self.assertIsNone(handle_update(self.engine, update))

    def test_non_text_update(self):
        result = handle_update(self.engine, {"message": {"chat": {"id": 42, "type": "private"}, "from": {"id": 42}, "photo": [{}]}})
        self.assertIn("текст", result[1])

    def test_message_limits(self):
        chunks = list(split_message("Одежда\n" * 1200))
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(x) <= 3500 for x in chunks))

    def test_api_request(self):
        client = TelegramClient("fake-token")
        with patch("telegram_bot.urlopen") as mocked:
            mocked.return_value.__enter__.return_value.read.return_value = b'{"ok":true,"result":[]}'
            self.assertEqual(client.call("getUpdates", offset=10, timeout=25), [])
            request = mocked.call_args.args[0]
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(json.loads(request.data)["offset"], 10)

    def test_network_error_does_not_expose_token(self):
        with patch("telegram_bot.urlopen", side_effect=URLError("https://api.telegram.org/botSECRET")):
            with self.assertRaises(TelegramError) as caught:
                TelegramClient("SECRET").call("getMe")
        self.assertNotIn("SECRET", str(caught.exception))

    def test_rate_limit(self):
        error = HTTPError("unused", 429, "limited", {}, BytesIO(b'{"ok":false,"error_code":429,"parameters":{"retry_after":2}}'))
        with patch("telegram_bot.urlopen", side_effect=error):
            with self.assertRaises(TelegramError) as caught:
                TelegramClient("fake").call("sendMessage", chat_id=42, text="hello")
        self.assertEqual(caught.exception.retry_after, 2)

    def test_polling_offset_survives(self):
        class FakeClient:
            offsets = []
            responses = []

            def call(self, method, **params):
                self.offsets.append(params["offset"])
                if len(self.offsets) > 1:
                    raise KeyboardInterrupt
                return [{"update_id": 30, "message": {"chat": {"id": 42, "type": "private"}, "from": {"id": 42}, "text": "привет"}}]

            def send(self, chat_id, text):
                self.responses.append((chat_id, text))
        client = FakeClient()
        with self.assertRaises(KeyboardInterrupt):
            run(client, self.engine)
        self.assertEqual(client.offsets, [0, 31])
        self.assertEqual(self.engine.store.load("__telegram_offset__")["offset"], 31)
        self.assertEqual(client.responses[0][0], 42)


if __name__ == "__main__":
    unittest.main(verbosity=2)
