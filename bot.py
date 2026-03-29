import sys
import os
import sqlite3
import logging
import string
import random
from datetime import datetime
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler, CallbackQueryHandler

sys.stdout = sys.stderr

TOKEN = "ВАШ_НОВЫЙ_ТОКЕН_ЗДЕСЬ"  
BOT_USERNAME = "rezhuBlyadeyBot"
ADMIN_ID = 7754721456

CATEGORIES = {
    "sh": "SH",
    "guro": "GURO",
    "suicide": "SUICIDE",
    "cartel": "CARTEL",
    "raznoe": "РАЗНОЕ"
}

SELECT_CATEGORY, ENTER_TITLE = range(2)

logging.basicConfig(level=logging.INFO)

def init_db():
    conn = sqlite3.connect('files.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            code TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            file_type TEXT NOT NULL,
            created_at TIMESTAMP,
            uploaded_by INTEGER,
            category TEXT,
            title TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_file(code, file_id, file_type, user_id, category, title):
    conn = sqlite3.connect('files.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO files (code, file_id, file_type, created_at, uploaded_by, category, title) VALUES (?, ?, ?, ?, ?, ?, ?)',
                   (code, file_id, file_type, datetime.now(), user_id, category, title))
    conn.commit()
    conn.close()

def get_file(code):
    conn = sqlite3.connect('files.db')
    cursor = conn.cursor()
    cursor.execute('SELECT file_id, file_type FROM files WHERE code = ?', (code,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_files_by_category():
    conn = sqlite3.connect('files.db')
    cursor = conn.cursor()
    cursor.execute('SELECT code, file_type, created_at, uploaded_by, category, title FROM files ORDER BY created_at DESC')
    rows = cursor.fetchall()
    conn.close()
    grouped = {cat: [] for cat in CATEGORIES.values()}
    grouped["Без категории"] = []
    for row in rows:
        code, file_type, created_at, uploaded_by, category, title = row
        cat = category if category in CATEGORIES.values() else "Без категории"
        grouped[cat].append((code, file_type, created_at, uploaded_by, title))
    return grouped

def get_user_files(user_id):
    conn = sqlite3.connect('files.db')
    cursor = conn.cursor()
    cursor.execute('SELECT code, file_type, created_at, category, title FROM files WHERE uploaded_by = ? ORDER BY created_at DESC', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def generate_code(length=8):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

pending_files = {}

async def start(update: Update, context: CallbackContext):
    args = context.args
    if args:
        code = args[0]
        file_info = get_file(code)
        if file_info:
            file_id, file_type = file_info
            if file_type == 'photo':
                await update.message.reply_photo(photo=file_id, caption="Вот ваш файл 📸")
            elif file_type == 'video':
                await update.message.reply_video(video=file_id, caption="Вот ваш файл 🎥")
            else:
                await update.message.reply_document(document=file_id, caption="Вот ваш файл 📄")
            return
        else:
            await update.message.reply_text("❌ Ссылка недействительна или файл удалён.")
    else:
        await update.message.reply_text(
            "Привет! Я бот-файлообменник.\n"
            "Отправьте мне фото или видео, затем выберите категорию и введите название.\n\n"
            "Команды:\n"
            "/list - список всех файлов (только админ)\n"
            "/myfiles - список ваших файлов\n"
            "/cancel - отменить загрузку"
        )

async def handle_file(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user

    if message.photo:
        file_type = 'photo'
        file_id = message.photo[-1].file_id
    elif message.video:
        file_type = 'video'
        file_id = message.video.file_id
    else:
        await message.reply_text("Пожалуйста, отправьте фото или видео.")
        return ConversationHandler.END

    pending_files[user.id] = (file_id, file_type, None, None)

    keyboard = []
    for key, cat_name in CATEGORIES.items():
        keyboard.append([InlineKeyboardButton(cat_name, callback_data=f"cat_{key}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text("Выберите категорию для этого файла:", reply_markup=reply_markup)
    return SELECT_CATEGORY

async def category_selected(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    cat_key = query.data.split('_')[1]
    category = CATEGORIES.get(cat_key, "РАЗНОЕ")

    if user.id not in pending_files:
        await query.edit_message_text("❌ Что-то пошло не так. Попробуйте отправить файл заново.")
        return ConversationHandler.END

    file_id, file_type, _, _ = pending_files[user.id]
    pending_files[user.id] = (file_id, file_type, category, None)

    await query.edit_message_text("Введите название для этого файла (текстом).")
    return ENTER_TITLE

async def title_entered(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user
    title = message.text.strip()

    if not title:
        await message.reply_text("Название не может быть пустым. Попробуйте снова или введите /cancel.")
        return ENTER_TITLE

    if user.id not in pending_files:
        await message.reply_text("❌ Что-то пошло не так. Попробуйте отправить файл заново.")
        return ConversationHandler.END

    file_id, file_type, category, _ = pending_files[user.id]
    if category is None:
        await message.reply_text("❌ Ошибка: категория не выбрана. Попробуйте заново.")
        return ConversationHandler.END

    code = generate_code()
    while get_file(code) is not None:
        code = generate_code()

    save_file(code, file_id, file_type, user.id, category, title)
    del pending_files[user.id]

    link = f"https://t.me/{BOT_USERNAME}?start={code}"
    keyboard = [[InlineKeyboardButton("📤 Получить файл", url=link)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await message.reply_text(
        f"✅ Файл *{title}* сохранён в категорию *{category}*!\n\n"
        f"🔗 Ваша ссылка:\n{link}\n\n"
        f"Отправьте эту ссылку кому угодно – по ней можно получить файл.",
        parse_mode="Markdown",
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )

    if user.id != ADMIN_ID:
        user_link = f"[{user.id}](tg://user?id={user.id})"
        if user.username:
            user_link = f"@{user.username}"
        notification_text = (
            f"📢 *Новый файл загружен!*\n\n"
            f"📝 Название: *{title}*\n"
            f"📁 Тип: {file_type.upper()}\n"
            f"📂 Категория: *{category}*\n"
            f"👤 От: {user_link}\n"
            f"🔗 Ссылка: [получить файл]({link})\n"
            f"🆔 Код: {code}"
        )
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=notification_text,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        except Exception as e:
            logging.error(f"Не удалось отправить уведомление админу: {e}")

    return ConversationHandler.END

async def cancel(update: Update, context: CallbackContext):
    user = update.effective_user
    if user.id in pending_files:
        del pending_files[user.id]
    await update.message.reply_text("Операция отменена. Вы можете отправить новый файл.")
    return ConversationHandler.END

async def list_files(update: Update, context: CallbackContext):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас нет прав для этой команды.")
        return

    grouped = get_files_by_category()
    total_files = sum(len(files) for files in grouped.values())

    if total_files == 0:
        await update.message.reply_text("📭 Нет загруженных файлов.")
        return

    message_text = "📋 *Список всех файлов по категориям:*\n\n"
    for cat, files in grouped.items():
        if not files:
            continue
        message_text += f"*{cat}* ({len(files)})\n"
        for idx, (code, file_type, created_at, uploaded_by, title) in enumerate(files[:5], 1):
            link = f"https://t.me/{BOT_USERNAME}?start={code}"
            date_str = created_at.strftime("%d.%m.%Y %H:%M")
            user_link = f"[{uploaded_by}](tg://user?id={uploaded_by})"
            display_name = title if title else file_type.upper()
            message_text += f"   {idx}. *{display_name}* – {date_str} – от {user_link} – [Ссылка]({link})\n"
        if len(files) > 5:
            message_text += f"   ... и ещё {len(files)-5} файлов.\n"
        message_text += "\n"
    message_text += f"*Всего файлов: {total_files}*"

    if len(message_text) > 4000:
        for i in range(0, len(message_text), 4000):
            await update.message.reply_text(message_text[i:i+4000], parse_mode="Markdown", disable_web_page_preview=True)
    else:
        await update.message.reply_text(message_text, parse_mode="Markdown", disable_web_page_preview=True)

async def myfiles(update: Update, context: CallbackContext):
    user = update.effective_user
    files = get_user_files(user.id)

    if not files:
        await update.message.reply_text("📭 У вас нет загруженных файлов.")
        return

    message_text = f"📁 *Ваши файлы* (всего {len(files)}):\n\n"
    for idx, (code, file_type, created_at, category, title) in enumerate(files[:20], 1):
        link = f"https://t.me/{BOT_USERNAME}?start={code}"
        date_str = created_at.strftime("%d.%m.%Y %H:%M")
        display_name = title if title else file_type.upper()
        cat_display = category if category else "без категории"
        message_text += f"{idx}. *{display_name}*\n"
        message_text += f"   📂 {cat_display}\n"
        message_text += f"   📅 {date_str}\n"
        message_text += f"   🔗 [Ссылка]({link})\n\n"

    if len(files) > 20:
        message_text += f"*Показаны первые 20 из {len(files)} файлов.*"

    if len(message_text) > 4000:
        for i in range(0, len(message_text), 4000):
            await update.message.reply_text(message_text[i:i+4000], parse_mode="Markdown", disable_web_page_preview=True)
    else:
        await update.message.reply_text(message_text, parse_mode="Markdown", disable_web_page_preview=True)

def run_bot():
    app = Application.builder().token(TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.PHOTO | filters.VIDEO, handle_file)],
        states={
            SELECT_CATEGORY: [CallbackQueryHandler(category_selected, pattern="^cat_")],
            ENTER_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, title_entered)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_files))
    app.add_handler(CommandHandler("myfiles", myfiles))
    app.run_polling()

flask_app = Flask(name)

@flask_app.route('/')
def index():
    return "Bot is running"

@flask_app.route('/health')
def health():
    return "OK"

if name == 'main':
    init_db()
    bot_thread = Thread(target=run_bot)
    bot_thread.start()
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host='0.0.0.0', port=port)
