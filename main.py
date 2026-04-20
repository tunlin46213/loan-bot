import os
import threading
from dotenv import load_dotenv
from openai import OpenAI
from flask import Flask
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters
)

# Load .env (local dev only; on Render use dashboard env vars)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

# Flask app (used by gunicorn via Procfile: gunicorn main:app)
app = Flask(__name__)

@app.route("/")
def health():
    return "Alive"

# Qwen / OpenRouter client
qwen_client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url="https://openrouter.ai/api/v1"
)

SYSTEM_PROMPT = """
You are a Cambodia real estate loan expert
assistant for bank staff.
Reply in the same language as the user.
"""

user_conversations = {}


async def start(update, context):
    await update.message.reply_text(
        "🏦 Cambodia Real Estate Loan Bot\n\n"
        "Ask me anything about loans, NBC rules,\n"
        "documents, or property valuation!"
    )


async def handle_message(update, context):
    user_id = update.effective_user.id
    user_text = update.message.text

    if user_id not in user_conversations:
        user_conversations[user_id] = []

    user_conversations[user_id].append({
        "role": "user",
        "content": user_text
    })

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    response = qwen_client.chat.completions.create(
        model="qwen/qwen-plus",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            *user_conversations[user_id]
        ]
    )

    bot_reply = response.choices[0].message.content

    user_conversations[user_id].append({
        "role": "assistant",
        "content": bot_reply
    })

    # Keep last 10 messages only
    if len(user_conversations[user_id]) > 10:
        user_conversations[user_id] = \
            user_conversations[user_id][-10:]

    await update.message.reply_text(bot_reply)


def start_flask():
    """Run the Flask health-check server (blocks the thread)."""
    port = int(os.getenv("PORT", 5000))
    # use_reloader=False is required inside a thread
    app.run(host="0.0.0.0", port=port, use_reloader=False)


def main():
    # Start Flask keep-alive server in a background daemon thread
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    # Start Telegram bot (long-polling)
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    print("✅ Bot is running...")
    bot_app.run_polling()


if __name__ == "__main__":
    main()