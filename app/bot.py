import os
import re
import json
import httpx
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_URL = "http://localhost:8000/api/v1/entries"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "🤖 **SKV Bot — Shared Knowledge Vault**\n\n"
        "Отправляй мне SKV-анкеты в формате JSON.\n\n"
        "Можешь:\n"
        "1. Отправить JSON текстом\n"
        "2. Отправить файл .json (скрепка 📎)\n\n"
        "Команды:\n"
        "/start - эта инструкция\n"
        "/help - помощь"
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📝 **Как использовать:**\n\n"
        "1. В диалоге с ИИ скажи: 'Сохрани это в SKV'\n"
        "2. ИИ сгенерирует JSON анкету\n"
        "3. Скопируй JSON и отправь мне ИЛИ\n"
        "4. Отправь файл .json\n"
        "5. Я валидирую и сохраню в базу\n\n"
        "После сохранения ты получишь:\n"
        "- ID записи\n"
        "- Публичную ссылку\n"
        "- Токен для удаления"
    )

@dp.message(lambda message: message.document)
async def handle_file(message: Message):
    """Обработка загруженных файлов"""
    try:
        file_id = message.document.file_id
        file = await bot.get_file(file_id)
        file_path = file.file_path
        downloaded_file = await bot.download_file(file_path)
        
        # Читаем JSON из файла
        json_str = downloaded_file.read().decode('utf-8')
        payload = json.loads(json_str)
        
        # Отправляем в API
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(API_URL, json=payload)
        
        if response.status_code == 201:
            result = response.json()
            await message.answer(
                f"✅ **Файл обработан!**\n\n"
                f"📝 ID: `{result['id']}`\n"
                f"🔗 Ссылка: {result['public_url']}\n\n"
                f"🔐 **Delete token (сохрани!):**\n"
                f"`{result['delete_token']}`\n\n"
                f"⚠️ Токен показан только один раз!"
            )
        else:
            await message.answer(
                f"❌ **Ошибка валидации:**\n\n"
                f"{response.text}"
            )
    except json.JSONDecodeError:
        await message.answer(
            "❌ Не удалось распарсить JSON.\n"
            "Отправь корректный JSON файл."
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message()
async def handle_json(message: Message):
    text = message.text
    
    # Ищем JSON между ```json и ```
    json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        json_str = text
    
    try:
        payload = json.loads(json_str)
        
        # Отправляем в API
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(API_URL, json=payload)
        
        if response.status_code == 201:
            result = response.json()
            await message.answer(
                f"✅ **Запись сохранена!**\n\n"
                f"📝 ID: `{result['id']}`\n"
                f"🔗 Ссылка: {result['public_url']}\n\n"
                f"🔐 **Delete token (сохрани!):**\n"
                f"`{result['delete_token']}`\n\n"
                f"⚠️ Токен показан только один раз!"
            )
        else:
            await message.answer(
                f"❌ **Ошибка валидации:**\n\n"
                f"{response.text}"
            )
    except json.JSONDecodeError:
        await message.answer(
            "❌ Не удалось распарсить JSON.\n"
            "Отправь корректную SKV-анкету в формате JSON."
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

async def main():
    await dp.start_polling(bot)