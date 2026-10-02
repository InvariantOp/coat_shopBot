"""Окно настройки: сохраняет токен в .env рядом с программой."""
import os
import re
from pathlib import Path


def save_token(token, path=None):
    token = token.strip()
    if not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{20,}", token):
        raise ValueError("Вставьте весь токен BotFather: цифры, двоеточие и длинная строка после него.")
    path = Path(path) if path else Path(__file__).with_name(".env")
    # При обновлении токена сохраняем пользовательские настройки базы.
    existing = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    lines = [line for line in existing if line.split("=", 1)[0].strip() != "TELEGRAM_TOKEN"]
    lines.append("TELEGRAM_TOKEN=" + token)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    os.replace(temporary, path)


def main():
    import tkinter as tk
    from tkinter import messagebox
    window = tk.Tk()
    window.title("CoatBot — настройка Telegram")
    window.geometry("600x280")
    window.resizable(False, False)
    tk.Label(window, text="Настройка Telegram", font=("Arial", 16, "bold")).pack(pady=(18, 10))
    tk.Label(window, text="1. Откройте вашего бота в @BotFather.\n"
                          "2. Скопируйте токен существующего бота coat_shopBot.\n"
                          "3. Вставьте токен ниже и нажмите «Сохранить токен».", justify="left", font=("Arial", 11)).pack()
    value = tk.StringVar()
    field = tk.Entry(window, textvariable=value, width=65, show="*", font=("Arial", 11))
    field.pack(pady=12)
    field.focus_set()

    def save():
        try:
            save_token(value.get())
        except (ValueError, OSError) as error:
            messagebox.showerror("Не удалось сохранить", str(error))
            return
        messagebox.showinfo("Готово", "Токен сохранён. Теперь запустите telegram_bot.py в PyCharm.\n"
                            "При запуске бот проверит подключение к Telegram.")
        window.destroy()

    tk.Button(window, text="Сохранить токен", command=save, font=("Arial", 11)).pack()
    tk.Label(window, text="Токен хранится только в файле .env на этом компьютере.", font=("Arial", 9)).pack(pady=10)
    window.mainloop()


if __name__ == "__main__":
    main()
