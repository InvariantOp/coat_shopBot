"""Учебный каталог. Замените модели, цены и размеры на данные магазина."""

CATEGORY_NAMES = {"jackets": "Куртки", "coats": "Пальто", "down": "Пуховики", "parkas": "Парки", "raincoats": "Плащи"}

PRODUCTS = [
    {"id": "J01", "name": "Куртка Urban", "category": "jackets", "season": "демисезон", "gender": "унисекс", "price": 4990, "sizes": [42, 44, 46, 48, 50, 52], "description": "Короткая куртка с подкладкой и двумя карманами."},
    {"id": "J02", "name": "Куртка Active", "category": "jackets", "season": "зима", "gender": "мужская", "price": 7990, "sizes": [46, 48, 50, 52, 54, 56], "description": "Утеплённая куртка с капюшоном и манжетами."},
    {"id": "C01", "name": "Пальто Classic", "category": "coats", "season": "демисезон", "gender": "женская", "price": 8990, "sizes": [40, 42, 44, 46, 48, 50], "description": "Прямое пальто длиной ниже колена, пояс в комплекте."},
    {"id": "C02", "name": "Пальто City", "category": "coats", "season": "демисезон", "gender": "мужская", "price": 10990, "sizes": [46, 48, 50, 52, 54], "description": "Однобортное пальто с воротником и подкладкой."},
    {"id": "D01", "name": "Пуховик Snow", "category": "down", "season": "зима", "gender": "женская", "price": 9990, "sizes": [42, 44, 46, 48, 50, 52], "description": "Удлинённый пуховик с капюшоном и застёжкой на молнию."},
    {"id": "D02", "name": "Пуховик North", "category": "down", "season": "зима", "gender": "унисекс", "price": 11990, "sizes": [44, 46, 48, 50, 52, 54, 56], "description": "Объёмный пуховик свободного кроя с высоким воротником."},
    {"id": "P01", "name": "Парка Weekend", "category": "parkas", "season": "демисезон", "gender": "унисекс", "price": 6490, "sizes": [42, 44, 46, 48, 50, 52, 54], "description": "Парка с кулиской на талии и вместительными карманами."},
    {"id": "P02", "name": "Парка Polar", "category": "parkas", "season": "зима", "gender": "мужская", "price": 9490, "sizes": [46, 48, 50, 52, 54, 56], "description": "Утеплённая парка с капюшоном и ветрозащитной планкой."},
    {"id": "R01", "name": "Плащ Breeze", "category": "raincoats", "season": "демисезон", "gender": "женская", "price": 5990, "sizes": [40, 42, 44, 46, 48, 50], "description": "Двубортный плащ с поясом для весны и осени."},
    {"id": "R02", "name": "Плащ Rain", "category": "raincoats", "season": "лето", "gender": "унисекс", "price": 3490, "sizes": [42, 44, 46, 48, 50, 52, 54, 56], "description": "Лёгкий плащ с капюшоном для прохладных летних дней."},
]


def get_product(product_id):
    return next((p for p in PRODUCTS if p["id"] == product_id.upper()), None)


def find_products(criteria):
    result = PRODUCTS
    for key in ("category", "season"):
        if criteria.get(key):
            result = [p for p in result if p[key] == criteria[key]]
    if criteria.get("gender"):
        result = [p for p in result if p["gender"] in (criteria["gender"], "унисекс")]
    if criteria.get("size"):
        result = [p for p in result if criteria["size"] in p["sizes"]]
    if criteria.get("budget") is not None:
        result = [p for p in result if p["price"] <= criteria["budget"]]
    return sorted(result, key=lambda p: (p["price"], p["id"]))


def format_product(p):
    return (f"{p['id']} · {p['name']} — {p['price']} ₽\n"
            f"{CATEGORY_NAMES[p['category']]} · {p['season']} · {p['gender']}\n"
            f"Размеры РФ: {', '.join(map(str, p['sizes']))}\n{p['description']}")
