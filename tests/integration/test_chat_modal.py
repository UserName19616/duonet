#!/usr/bin/env python3
"""
Скрипт для автоматического тестирования страницы чата и логирования модальных окон.
Запускать при работающем сервере (./run_web.sh)
"""

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


async def main():
    # НАСТРОЙКИ - ИЗМЕНИ ПОД СЕБЯ
    API_URL = "https://localhost:8443"

    # ВАЖНО: для чата нужен КЛИЕНТСКИЙ аккаунт (без .srv в конце)
    TEST_USER = {
        "public_id": "@K7MC-57UH-URW7.ru",      # Клиентский ID (без .srv)
        "seed_phrase": "lehanik@inbox.ru",
        "password": "12345678"
    }

    # ID контакта (тоже клиентский, без .srv)
    CONTACT_ID = "@EQSW-MBWC-CFM8.ru"

    log_file = Path("chat_test_log.txt")
    screenshot_dir = Path("chat_screenshots")
    screenshot_dir.mkdir(exist_ok=True)

    def log(msg, level="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [{level}] {msg}\n")
        print(f"[{timestamp}] [{level}] {msg}")

    log("=" * 60)
    log("НАЧАЛО ТЕСТИРОВАНИЯ ЧАТА")
    log(f"Contact ID: {CONTACT_ID}")
    log(f"User: {TEST_USER['public_id']}")
    log("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        console_logs = []

        def on_console(msg):
            text = msg.text
            console_logs.append({
                "type": msg.type,
                "text": text,
                "timestamp": time.time()
            })
            short_text = text[:200] + "..." if len(text) > 200 else text
            log(f"[CONSOLE {msg.type}] {short_text}")

        def on_page_error(error):
            log(f"[PAGE ERROR] {error}", "ERROR")

        page.on("console", on_console)
        page.on("pageerror", on_page_error)

        async def handle_dialog(dialog):
            log(f"[DIALOG] {dialog.type}: {dialog.message}", "WARNING")
            await dialog.dismiss()
            timestamp = int(time.time())
            screenshot_path = screenshot_dir / f"dialog_{timestamp}.png"
            await page.screenshot(path=str(screenshot_path))
            log(f"[SCREENSHOT] Saved: {screenshot_path}")

        page.on("dialog", handle_dialog)

        # 1. Заходим на страницу accounts
        log("1. Загрузка страницы accounts...")
        await page.goto(f"{API_URL}/accounts", wait_until="networkidle")
        await page.screenshot(path=str(screenshot_dir / "01_accounts.png"))

        # 2. Ищем КЛИЕНТСКИЙ аккаунт (без .srv)
        log(f"2. Поиск клиентского аккаунта: {TEST_USER['public_id']}")

        await page.wait_for_selector("div.cursor-pointer", timeout=10000)

        account_found = False
        accounts = await page.query_selector_all("div.cursor-pointer")

        for acc in accounts:
            text = await acc.inner_text()
            # Ключевое условие: выбираем ТОЛЬКО аккаунт без .srv
            if TEST_USER["public_id"] in text and ".srv" not in text:
                await acc.click()
                account_found = True
                log(f"   ✅ Клиентский аккаунт найден и кликнут")
                log(f"   Текст элемента: {text[:100]}")
                break

        if not account_found:
            log(f"   ❌ Клиентский аккаунт не найден!", "ERROR")
            log(f"   Доступные аккаунты:")
            for acc in accounts:
                text = await acc.inner_text()
                log(f"      - {text[:100]}")
            await browser.close()
            return

        # Ждем модальное окно входа
        try:
            await page.wait_for_selector("#loginModal", timeout=5000)
            log("3. Модальное окно входа появилось")
        except PlaywrightTimeoutError:
            log("3. Модальное окно входа НЕ появилось (возможно, уже залогинены)", "WARNING")

        await page.screenshot(path=str(screenshot_dir / "02_login_modal.png"))

        # 4. Заполняем форму входа
        log("4. Заполнение формы входа...")
        await page.fill("#modal_seed", TEST_USER["seed_phrase"])
        await page.fill("#modal_password", TEST_USER["password"])
        await page.screenshot(path=str(screenshot_dir / "03_login_filled.png"))

        # 5. Отправляем форму
        log("5. Отправка формы...")
        await page.click("#modal_submit")

        # 6. Ждем перехода на страницу чата (НЕ monitor!)
        log("6. Ожидание перехода на /chat...")

        try:
            await page.wait_for_url(lambda url: "/chat" in url, timeout=10000)
        except PlaywrightTimeoutError:
            current_url = page.url
            log(f"   ❌ Не удалось перейти на /chat. Текущий URL: {current_url}", "ERROR")
            if "/monitor" in current_url:
                log("   ❌ Попали на /monitor (выбран серверный аккаунт)!", "ERROR")
            await page.screenshot(path=str(screenshot_dir / "04_error.png"))
            await browser.close()
            return

        log(f"   ✅ Текущий URL: {page.url}")
        await page.screenshot(path=str(screenshot_dir / "04_chat_list.png"))

        # 7. Кликаем по контакту
        log(f"7. Поиск контакта: {CONTACT_ID}")

        await page.wait_for_selector(".cursor-pointer", timeout=10000)

        contact_found = False
        contacts = await page.query_selector_all(".cursor-pointer")
        for contact in contacts:
            text = await contact.inner_text()
            if CONTACT_ID in text:
                await contact.click()
                contact_found = True
                log(f"   Контакт найден и кликнут")
                break

        if not contact_found:
            log(f"   Контакт не найден!", "WARNING")
            log(f"   Доступные контакты:")
            for contact in contacts:
                text = await contact.inner_text()
                log(f"      - {text[:100]}")
            await browser.close()
            return

        # 8. Ожидаем загрузки страницы чата
        log("8. Ожидание загрузки страницы чата...")
        await asyncio.sleep(5)

        for i in range(5):
            await asyncio.sleep(1)
            await page.screenshot(path=str(screenshot_dir / f"05_chat_{i}.png"))
            log(f"   Скриншот {i+1}/5 сохранен")

        # 9. Проверяем наличие модальных окон
        log("\n9. ПРОВЕРКА МОДАЛЬНЫХ ОКОН:")
        modal_ids = ["phraseModal", "errorModal", "confirmModal", "systemMessageModal"]

        for modal_id in modal_ids:
            modal = await page.query_selector(f"#{modal_id}")
            if modal:
                is_visible = await modal.is_visible()
                if is_visible:
                    log(f"   ❌ Модальное окно {modal_id} ОТКРЫТО!", "WARNING")
                    await page.screenshot(path=str(screenshot_dir / f"modal_{modal_id}.png"))
                    text_content = await modal.inner_text()
                    log(f"      Содержимое: {text_content[:200]}")
                else:
                    log(f"   ✅ Модальное окно {modal_id} закрыто")
            else:
                log(f"   ✅ Модальное окно {modal_id} не найдено в DOM")

        # 10. Анализируем консольные логи
        log("\n10. АНАЛИЗ КОНСОЛЬНЫХ ЛОГОВ:")

        modal_triggers = []
        errors = []

        for log_entry in console_logs:
            text = log_entry["text"]

            if "MODAL" in text or "modal" in text.lower():
                modal_triggers.append(log_entry)
                log(f"   [MODAL TRIGGER] {text[:150]}")

            if "error" in text.lower() or "Error" in text:
                errors.append(log_entry)
                log(f"   [ERROR] {text[:150]}")

        # 11. Итоговый отчет
        log("\n" + "=" * 60)
        log("ИТОГОВЫЙ ОТЧЕТ")
        log("=" * 60)
        log(f"Всего консольных сообщений: {len(console_logs)}")
        log(f"Из них ошибок: {len(errors)}")
        log(f"Событий, связанных с модальными окнами: {len(modal_triggers)}")

        with open(log_file, "a", encoding="utf-8") as f:
            f.write("\n\n" + "=" * 60 + "\n")
            f.write("ПОЛНЫЙ КОНСОЛЬНЫЙ ЛОГ\n")
            f.write("=" * 60 + "\n")
            for log_entry in console_logs:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        log(f"\n📁 Лог сохранен: {log_file}")
        log(f"📁 Скриншоты: {screenshot_dir}")

        log("\nНажми Enter для закрытия браузера...")
        input()

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
