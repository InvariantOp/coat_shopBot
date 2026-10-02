"""Консольный режим и независимая от Telegram логика диалога."""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.svm import LinearSVC

from bot_config import BOT_CONFIG
from products import CATEGORY_NAMES, PRODUCTS, find_products, format_product, get_product
from storage import Store


def order_date(value):
    """В базе даты хранятся в UTC, в заказах показываются по Москве."""
    date = datetime.fromisoformat(value)
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return date.astimezone(timezone(timedelta(hours=3))).strftime("%d.%m.%Y")


def clear_phrase(text):
    return re.sub(r"\s+", " ", re.sub(r"[^а-яa-z0-9\s]", " ", text.lower().replace("ё", "е"))).strip()


class IntentModel:
    def __init__(self):
        phrases, labels = [], []
        for intent, data in BOT_CONFIG["intents"].items():
            for phrase in data["examples"]:
                phrases.append(clear_phrase(phrase))
                labels.append(intent)
        self.vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(3, 5))
        self.examples = self.vectorizer.fit_transform(phrases)
        self.labels = labels
        self.classifier = LinearSVC(random_state=42)
        self.classifier.fit(self.examples, labels)
        self.exact = dict(zip(phrases, labels))

    def classify(self, text):
        text = clear_phrase(text)
        if text in self.exact:
            return self.exact[text]
        vector = self.vectorizer.transform([text])
        predicted = self.classifier.predict(vector)[0]
        similarities = cosine_similarity(vector, self.examples)[0]
        # Порог проверяется для предсказанного класса, а не любого примера.
        score = max((s for s, label in zip(similarities, self.labels) if label == predicted), default=0)
        return predicted if score >= 0.50 else None


def load_dialogues():
    content = Path(__file__).with_name("dialogues.txt").read_text(encoding="utf-8")
    result, seen = [], set()
    for block in re.split(r"\n\s*\n", content):
        lines = block.strip().splitlines()
        if len(lines) >= 2 and lines[0].startswith("Q:") and lines[1].startswith("A:"):
            question, answer = clear_phrase(lines[0][2:]), lines[1][2:].strip()
            if question and answer and question not in seen:
                result.append((question, answer))
                seen.add(question)
    return result


def edit_distance(left, right):
    """Расстояние Левенштейна для обработки небольших опечаток."""
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        row = [i]
        for j, b in enumerate(right, 1):
            row.append(min(row[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = row
    return previous[-1]


def detect_soft_ad(text):
    """Связывает тему беседы с одеждой; показ товаров требует согласия."""
    t = clear_phrase(text)
    if re.search(r"\bне\s+(?:холодно|мерзну|замерз)", t):
        return None
    scenarios = [
        (r"\b(холодно|мерзну|замерз|замерза|мороз|зим)", "down", "зима",
         "В холодную погоду хочется больше тепла и комфорта.",
         "Для таких дней в каталоге есть зимние пуховики. Хотите подобрать несколько вариантов?"),
        (r"\b(дожд|промок|ливень)", "raincoats", "демисезон",
         "Дождь может изменить планы на прогулку.",
         "В каталоге есть плащи для весны и осени. Хотите посмотреть подходящие модели?"),
        (r"\b(осен|осень|весн|весен|похолод)", "jackets", "демисезон",
         "В межсезонье погода часто меняется в течение дня.",
         "Для прохладных дней можно подобрать демисезонную куртку. Хотите посмотреть варианты?"),
        (r"\b(гуля|прогул|пройтись|природ)", "parkas", "демисезон",
         "Прогулка помогает сменить обстановку и отвлечься от повседневных дел.",
         "Если нужна одежда для прохладной погоды, можно посмотреть парки. Хотите подобрать модель?"),
    ]
    for pattern, category, season, answer, bridge in scenarios:
        if re.search(pattern, t):
            return {"category": category, "season": season, "answer": answer, "bridge": bridge}
    return None


HELP = ("Я подбираю верхнюю одежду по категории, сезону, размеру и бюджету.\n"
        "Можем поговорить об учёбе, работе, хобби и погоде. Рекомендации товаров можно отклонить или отключить фразой «без рекламы».\n"
        "Каталог — показать все модели. Подобрать одежду — пошаговый подбор.\n"
        "Можно сразу написать: «женская зимняя куртка размер 46 до 10000».\n"
        "После показа моделей выберите их номер или напишите «купить J01».\n"
        "Корзина — показать выбранное. Удалить 1 — удалить позицию. Очистить корзину — удалить всё.\n"
        "Оформить заказ — оставить заявку. Мои заказы — посмотреть свои заявки.\n"
        "Отмена — прервать подбор или оформление. Начать заново — сбросить подбор.\n"
        "Выберите действие на клавиатуре или напишите свой запрос.")


def parse_criteria(text):
    text = clear_phrase(text)
    result = {}
    roots = {"jackets": ["куртк", "ветровк"], "coats": ["пальто"],
             "down": ["пуховик"], "parkas": [r"парк(?:а|и|у|ой|ами|ах)\b"], "raincoats": ["плащ", "дождевик"]}
    for category, words in roots.items():
        if any(re.search(r"\b" + word, text) for word in words):
            result["category"] = category
            break
    if re.search(r"\b(демисезон|осен|весен|осень|весн)", text):
        result["season"] = "демисезон"
    elif re.search(r"\bзим", text):
        result["season"] = "зима"
    elif re.search(r"\b(лето|летн)", text):
        result["season"] = "лето"
    if re.search(r"\b(женск|женщин|девуш)", text):
        result["gender"] = "женская"
    elif re.search(r"\b(мужск|мужчин|парн)", text):
        result["gender"] = "мужская"
    budget = re.search(r"\b(?:до|бюджет(?:ом)?|не дороже)\s*(\d{1,6}(?:\s\d{3})?)(?!\d)\s*(тыс|к\b)?", text)
    # Число из бюджета (например, «до 50 тыс») не является размером.
    size_text = text[:budget.start()] + text[budget.end():] if budget else text
    size = re.search(r"\bразмер(?:а|ом)?\s*(\d{2})\b", size_text)
    if not size:
        size = re.search(r"\b(40|42|44|46|48|50|52|54|56)\b", size_text)
    if size:
        result["size"] = int(size.group(1))
    if budget:
        result["budget"] = int(budget.group(1).replace(" ", "")) * (1000 if budget.group(2) else 1)
    return result


class ShopBot:
    def __init__(self, store=None):
        self.store = store or Store()
        self.model = IntentModel()
        self.dialogues = load_dialogues()

    def reply(self, text, user_id="console"):
        if not isinstance(text, str) or not text.strip():
            return "Напишите сообщение или выберите кнопку."
        if len(text) > 1000:
            return "Сообщение слишком длинное. Напишите запрос до 1000 символов."
        state = self.store.load(user_id)
        answer = self._reply(text.strip(), state, user_id)
        self.store.save(user_id, state)
        return answer

    @staticmethod
    def reset(state):
        state.update(stage=None, criteria={}, shown=[], draft={})
        state.pop("selected", None)
        state.pop("offer", None)

    def dialogue_answer(self, text):
        text = clear_phrase(text)
        if not text:
            return None
        for question, answer in self.dialogues:
            if text == question:
                return answer
        best, score = None, 1.0
        for question, answer in self.dialogues:
            if abs(len(text) - len(question)) / max(len(text), len(question)) > 0.25:
                continue
            distance = edit_distance(text, question) / max(len(text), len(question))
            if distance < score:
                best, score = answer, distance
        return best if score <= 0.20 else None

    def show(self, state, criteria):
        products = find_products(criteria)
        state["criteria"] = criteria
        state["shown"] = [p["id"] for p in products]
        state["stage"] = "choose" if products else None
        if not products:
            return ("По этим условиям моделей нет. Размер и бюджет не были изменены.\n"
                    "Попробуйте другие условия или напишите «Каталог».")
        return "\n\n".join(["Каталог верхней одежды:"] + [f"{i}. {format_product(p)}" for i, p in enumerate(products, 1)]) + "\n\nВыберите номер модели или напишите «купить J01»."

    def next_question(self, state):
        c = state["criteria"]
        for key, prompt in [
            ("category", "Что подбираем? Куртки, пальто, пуховики, парки или плащи. Можно написать «любая категория»."),
            ("season", "На какой сезон? Зима, демисезон или лето. Можно написать «любой сезон»."),
            ("size", "Какой российский размер? Например, 46. Можно написать «любой размер»."),
            ("budget", "Какой максимальный бюджет в рублях? Например, 10000. Можно написать «без ограничения»."),
        ]:
            if key not in c:
                state["stage"] = key
                return prompt
        return self.show(state, c)

    def cart(self, state):
        if not state["cart"]:
            return "Корзина пуста. Откройте «Каталог» и выберите модель."
        lines, total = [], 0
        for i, item in enumerate(state["cart"], 1):
            p = get_product(item["id"])
            subtotal = p["price"] * item["quantity"]
            total += subtotal
            lines.append(f"{i}. {p['name']} ({p['id']}), размер {item['size']}, {item['quantity']} шт. — {subtotal} ₽")
        return "Корзина:\n" + "\n".join(lines) + f"\nИтого за товары: {total} ₽\n«Оформить заказ» — оставить заявку. «Удалить 1» — убрать позицию."

    def add(self, state, product_id, size):
        p = get_product(product_id)
        if not p or size not in p["sizes"]:
            return "Такой модели или размера нет в каталоге."
        item = next((x for x in state["cart"] if x["id"] == p["id"] and x["size"] == size), None)
        if item and item["quantity"] >= 10:
            return "В одном заказе можно выбрать до 10 штук одной модели и размера."
        if item:
            item["quantity"] += 1
        else:
            state["cart"].append({"id": p["id"], "size": size, "quantity": 1})
        state["stage"] = "choose"
        state.pop("selected", None)
        return f"Добавлено: {p['name']}, размер {size}.\n\n" + self.cart(state)

    def select_product(self, state, product_id):
        p = get_product(product_id)
        if not p:
            return "Модель не найдена. Проверьте код, например J01."
        size = state["criteria"].get("size")
        if size in p["sizes"]:
            return self.add(state, p["id"], size)
        state.update(stage="product_size", selected=p["id"])
        return f"Вы выбрали {p['name']}. Укажите размер: {', '.join(map(str, p['sizes']))}."

    def _reply(self, text, s, user_id):
        t = clear_phrase(text)
        command = text.split()[0].lower().split("@")[0]
        if command in ("/start", "/reset") or t == "начать заново":
            self.reset(s)
            s["ads_paused"] = False
            return BOT_CONFIG["intents"]["hello"]["responses"][0] + "\nКорзина сохранена."
        if command == "/cancel" or t in ("отмена", "отменить"):
            self.reset(s)
            return "Текущий подбор или оформление отменены. Корзина сохранена."
        if command == "/help" or t in ("помощь", "что ты умеешь"):
            return HELP
        if t in ("без рекламы", "не предлагай товары", "не хочу ничего покупать", "давай без рекламы"):
            s["ads_paused"] = True
            if s["stage"] == "ad_offer":
                self.reset(s)
            return "Хорошо, продолжим общение без рекламных предложений. Каталог можно открыть самостоятельно."
        if command == "/catalog" or t in ("каталог", "покажи каталог", "ассортимент"):
            self.reset(s)
            return self.show(s, {})
        if t in ("подобрать одежду", "подбор", "помоги выбрать одежду"):
            self.reset(s)
            return self.next_question(s)
        if command == "/cart" or t == "корзина":
            return self.cart(s)
        if t == "очистить корзину":
            s["cart"] = []
            self.reset(s)
            return "Корзина очищена."
        remove = re.fullmatch(r"удалить\s+(\d+)", t)
        if remove:
            index = int(remove.group(1)) - 1
            if not 0 <= index < len(s["cart"]):
                return "Такого номера в корзине нет."
            s["cart"].pop(index)
            self.reset(s)
            return self.cart(s)
        if command == "/orders" or t == "мои заказы":
            orders = self.store.orders(user_id)
            if not orders:
                return "У вас пока нет заказов."
            return "Ваши заказы:\n" + "\n".join(f"№{i} · {order_date(date)} · {data['total']} ₽ · оформлен, без оплаты" for i, date, data in orders)
        if command == "/checkout" or t in ("оформить заказ", "оформить", "заказать"):
            if not s["cart"]:
                return self.cart(s)
            s.update(stage="customer_name", draft={})
            return "Оформим заказ. Как к вам обращаться?"
        if s["stage"] == "ad_offer":
            if t in ("да", "давай", "покажи", "хочу", "конечно", "хорошо", "да давай", "да покажи"):
                s["criteria"] = s.pop("offer")
                return self.next_question(s)
            if t in ("нет", "не надо", "не хочу", "не нужно"):
                self.reset(s)
                s["ads_paused"] = True
                return "Хорошо, товары показывать не буду. Можем продолжить разговор."
            # Новый вопрос прекращает предложение, а не запирает пользователя в нём.
            self.reset(s)
        # Данные оформления не передаются классификатору намерений.
        stage = s["stage"]
        if stage == "customer_name":
            if not 2 <= len(text) <= 80 or not re.search(r"[а-яА-ЯёЁa-zA-Z]", text):
                return "Введите имя длиной от 2 до 80 символов."
            s["draft"]["name"] = text
            s["stage"] = "phone"
            return "Введите контактный телефон: от 10 до 15 цифр, например +79991234567."
        if stage == "phone":
            phone = re.sub(r"[\s()\-]", "", text)
            if not re.fullmatch(r"\+?\d{10,15}", phone):
                return "Не удалось проверить телефон. Введите 10–15 цифр; можно использовать +, пробелы, скобки и дефисы."
            s["draft"]["phone"] = phone
            s["stage"] = "city"
            return "Укажите город. Адрес доставки на этом этапе не нужен."
        if stage == "city":
            if not 2 <= len(text) <= 100 or not re.search(r"[а-яА-ЯёЁa-zA-Z]", text):
                return "Введите название города длиной от 2 до 100 символов."
            s["draft"]["city"] = text
            s["stage"] = "confirm"
            d = s["draft"]
            return self.cart(s) + f"\n\nИмя: {d['name']}\nТелефон: {d['phone']}\nГород: {d['city']}\n\nПодтвердить заказ? Ответьте «Да» или «Нет»."
        if stage == "confirm":
            if t in ("нет", "не надо"):
                self.reset(s)
                return "Оформление отменено. Корзина сохранена."
            if t not in ("да", "подтвердить"):
                return "Ответьте «Да» для сохранения заявки или «Нет» для отмены."
            items = [{**x, "name": get_product(x["id"])["name"], "price": get_product(x["id"])["price"]} for x in s["cart"]]
            order = {**s["draft"], "items": items, "total": sum(x["price"] * x["quantity"] for x in items), "status": "заявка без оплаты"}
            s["cart"] = []
            self.reset(s)
            number = self.store.place_order(user_id, s, order)
            return f"Заказ №{number} оформлен. Сумма товаров: {order['total']} ₽.\nЗаказ доступен в разделе «Мои заказы»."
        codes = list(dict.fromkeys(re.findall(r"\b[a-z]\d{2}\b", t)))
        if len(codes) > 1:
            examples = " или ".join(f"«купить {code.upper()}»" for code in codes)
            return f"Вы указали несколько моделей. Выберите одну: {examples}."
        buy = re.fullmatch(r"(?:(?:купить|добавить)\s+)?([a-z]\d{2})(?:\s+(?:купить|добавить))?(?:\s+(\d{2}))?", t)
        if buy:
            return self.add(s, buy.group(1), int(buy.group(2))) if buy.group(2) else self.select_product(s, buy.group(1))
        if stage == "product_size":
            p = get_product(s["selected"])
            size = parse_criteria(t).get("size")
            if size not in p["sizes"]:
                return f"Для {p['name']} доступны размеры: {', '.join(map(str, p['sizes']))}. Выберите один или напишите «Отмена»."
            return self.add(s, p["id"], size)
        if stage == "choose" and t.isdigit():
            index = int(t) - 1
            if 0 <= index < len(s["shown"]):
                return self.select_product(s, s["shown"][index])
            return "Такого номера в показанном списке нет. Выберите номер модели или откройте «Каталог»."
        if stage in ("category", "season", "size", "budget"):
            if stage == "budget" and re.search(r"-\s*\d", text):
                return "Бюджет должен быть больше нуля. Например, 10000."
            c = parse_criteria(text)
            skip = t in ("любой", "любая", "все", "пропустить", "любая категория", "любой сезон", "любой размер", "без ограничения", "не важно", "неважно")
            if skip:
                c[stage] = None
            elif stage == "budget" and re.fullmatch(r"\d+(?:\s\d{3})?", t):
                c["budget"] = int(t.replace(" ", ""))
            if stage == "size" and c.get("size") not in (None, 40, 42, 44, 46, 48, 50, 52, 54, 56):
                return "В каталоге размеры РФ от 40 до 56 с шагом 2. Выберите размер или напишите «любой размер»."
            if c.get("budget") is not None and c["budget"] <= 0:
                return "Бюджет должен быть больше нуля. Например, 10000."
            if stage not in c:
                # Информационные вопросы не уничтожают незавершённый подбор.
                intent = self.model.classify(t)
                answer = self.dialogue_answer(t)
                if not answer and intent and BOT_CONFIG["intents"][intent]["responses"]:
                    answer = BOT_CONFIG["intents"][intent]["responses"][0]
                if intent == "bye":
                    self.reset(s)
                    return answer
                if answer:
                    return answer + "\n\n" + self.next_question(s)
                return self.next_question(s)
            s["criteria"].update(c)
            return self.next_question(s)
        criteria = parse_criteria(text)
        ad = detect_soft_ad(text)
        # Прямой запрос модели или её параметров имеет приоритет над рекламой.
        if ad and not any(key in criteria for key in ("category", "size", "budget", "gender")):
            answer = self.dialogue_answer(t) or ad["answer"]
            if s.get("ads_paused"):
                return answer
            self.reset(s)
            s.update(stage="ad_offer", offer={"category": ad["category"], "season": ad["season"]})
            return answer + "\n\n" + ad["bridge"] + "\nОтветьте «Да» или «Нет»."
        answer = self.dialogue_answer(t)
        if answer:
            return answer
        if criteria:
            self.reset(s)
            return self.show(s, criteria)
        intent = self.model.classify(t)
        if intent == "catalog":
            self.reset(s)
            return self.show(s, {})
        if intent == "select":
            self.reset(s)
            return self.next_question(s)
        if intent == "help":
            return HELP
        if intent:
            if intent == "bye":
                self.reset(s)
            return BOT_CONFIG["intents"][intent]["responses"][0]
        return BOT_CONFIG["failure_phrases"][0]


def main():
    engine = ShopBot()
    print("CoatBot — магазин верхней одежды. Для завершения: выход.")
    try:
        while True:
            text = input("\nВы: ")
            if clear_phrase(text) in ("выход", "exit"):
                break
            print("\nCoatBot:", engine.reply(text))
    except (EOFError, KeyboardInterrupt):
        print("\nДо встречи!")
    finally:
        engine.store.close()


if __name__ == "__main__":
    main()
