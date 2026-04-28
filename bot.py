"""SKV Network Telegram Bot — with SOCKS5 proxy"""
import asyncio, json, urllib.request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = "8728719042:AAGaSb-myFDxAR9dCr9c-VuE5p4d674cWrc"
SKV_API = "https://skv.network/api/v2/entries"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "SKV Network Bot\n\nSend .json file with project\nWeb: https://skv.network"
    )

async def handle_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Processing...")
    try:
        file = await update.message.document.get_file()
        content = await file.download_as_bytearray()
        data = json.loads(content)
        body = json.dumps(data).encode()
        req = urllib.request.Request(SKV_API, data=body, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        
        msg = "OK! ID: " + str(result.get("id", "?"))
        cons = result.get("consultation", {})
        if cons.get("answer"):
            msg += "\n\n" + str(cons["answer"])[:1500]
        
        files = result.get("files", [])
        if files:
            msg += "\n\nFiles:"
            for f in files:
                if f.get("url"):
                    msg += "\n  https://skv.network" + f["url"]
        
        await update.message.reply_text(msg[:4000])
    except Exception as e:
        await update.message.reply_text("Error: " + str(e)[:500])

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send .json file or visit https://skv.network")

def main():
    app = Application.builder().token(TOKEN).proxy("socks5://127.0.0.1:1080").build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.FileExtension("json"), handle_json))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Bot started with SOCKS5")
    app.run_polling()

if __name__ == "__main__":
    main()
