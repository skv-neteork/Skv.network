from aiogram.types import Message, ContentType

# Добавь этот хендлер ПЕРЕД handle_json

@dp.message(lambda message: message.document)
async def handle_file(message: Message):
    """Обработка загруженных файлов"""
    file_id = message.document.file_id
    file = await bot.get_file(file_id)
    file_path = file.file_path
    downloaded_file = await bot.download_file(file_path)
    
    # Читаем JSON из файла
    try:
        import json
        json_str = downloaded_file.read().decode('utf-8')
        payload = json.loads(json_str)
        
        # Отправляем в API (как в handle_json)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(API_URL, json=payload)
        
        if response.status_code == 201:
            result = response.json()
            await message.answer(
                f"✅ **Файл обработан!**\n\n"
                f"📝 ID: `{result['id']}`\n"
                f"🔗 Ссылка: {result['public_url']}\n\n"
                f"🔐 **Delete token:**\n"
                f"`{result['delete_token']}`"
            )
        else:
            await message.answer(f"❌ Ошибка: {response.text}")
    except Exception as e:
        await message.answer(f"❌ Ошибка чтения файла: {str(e)}")