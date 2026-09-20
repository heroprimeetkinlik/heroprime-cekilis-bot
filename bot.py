```python
import os
import sqlite3
import secrets
import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)


# =========================================================
# AYARLAR
# =========================================================

# BOT TOKEN KODUN İÇİNE YAZILMAZ.
# Railway Variables üzerinden alınır.
BOT_TOKEN = '8855111211:AAFhY9oBPMEAR9jDd1WhwN2nZmFpZXMUX4s'

# Railway Variables:
# ADMIN_IDS=8845737995
#
# Birden fazla admin:
# ADMIN_IDS=8845737995,123456789
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()

# =========================================================
# SADECE BU TELEGRAM GRUBUNDA ÇALIŞIR
# =========================================================

ALLOWED_GROUP_USERNAME = "heroprimesohbet"

# Railway Volume kullanırsan buraya volume yolunu verebilirsin.
DB_FILE = os.getenv("DB_FILE", "giveaway.db")


# =========================================================
# LOG
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# ADMIN KONTROLÜ
# =========================================================

def get_admin_ids():
    admin_ids = set()

    if not ADMIN_IDS_RAW:
        return admin_ids

    for value in ADMIN_IDS_RAW.split(","):
        value = value.strip()

        if not value:
            continue

        try:
            admin_ids.add(int(value))
        except ValueError:
            logger.warning(
                "Geçersiz ADMIN_IDS değeri: %s",
                value,
            )

    return admin_ids


ADMIN_IDS = get_admin_ids()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# =========================================================
# GRUP KONTROLÜ
# =========================================================

def is_allowed_group(update: Update) -> bool:
    """
    Botun sadece @heroprimesohbet grubunda
    çalışmasına izin verir.
    """

    chat = update.effective_chat

    if not chat:
        return False

    if chat.type not in ("group", "supergroup"):
        return False

    username = (chat.username or "").lower()

    return username == ALLOWED_GROUP_USERNAME.lower()


# =========================================================
# DATABASE
# =========================================================

def get_db():
    connection = sqlite3.connect(DB_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def init_database():
    connection = get_db()
    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            started_by INTEGER NOT NULL,
            winner_count INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            ended_at TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            giveaway_id INTEGER NOT NULL,
            telegram_user_id INTEGER NOT NULL,
            telegram_username TEXT,
            telegram_name TEXT NOT NULL,
            entered_username TEXT NOT NULL,
            joined_at TEXT NOT NULL,

            UNIQUE(giveaway_id, telegram_user_id),

            FOREIGN KEY(giveaway_id)
                REFERENCES giveaways(id)
        )
        """
    )

    connection.commit()
    connection.close()


# =========================================================
# AKTİF ÇEKİLİŞ
# =========================================================

def get_active_giveaway():
    connection = get_db()

    row = connection.execute(
        """
        SELECT *
        FROM giveaways
        WHERE active = 1
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    connection.close()

    return row


def get_participant_count(giveaway_id: int) -> int:
    connection = get_db()

    row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM participants
        WHERE giveaway_id = ?
        """,
        (giveaway_id,),
    ).fetchone()

    connection.close()

    return int(row["count"])


# =========================================================
# ÇEKİLİŞ MESAJI
# =========================================================

def build_giveaway_text(
    winner_count: int,
    participant_count: int,
):
    return (
        "🎉 <b>ÇEKİLİŞ BAŞLADI!</b>\n\n"
        f"🏆 Kazanan sayısı: <b>{winner_count}</b>\n"
        f"👥 Katılımcı: <b>{participant_count}</b>\n\n"
        "Katılmak için <b>bu mesaja yanıt vererek</b>:\n"
        "<code>/katil kullanıcı_adınız</code>\n"
        "yazın.\n\n"
        "🟢 <b>Çekiliş aktif.</b>\n"
        "🛑 Çekiliş yalnızca admin tarafından "
        "<code>/stopcekilis</code> komutuyla bitirilir."
    )


async def update_giveaway_message(
    context: ContextTypes.DEFAULT_TYPE,
    giveaway,
):
    participant_count = get_participant_count(
        giveaway["id"]
    )

    text = build_giveaway_text(
        giveaway["winner_count"],
        participant_count,
    )

    try:
        await context.bot.edit_message_text(
            chat_id=giveaway["chat_id"],
            message_id=giveaway["message_id"],
            text=text,
            parse_mode="HTML",
        )

    except Exception as error:
        logger.warning(
            "Çekiliş mesajı güncellenemedi: %s",
            error,
        )


# =========================================================
# /myid
# =========================================================

async def my_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.effective_user or not update.message:
        return

    user = update.effective_user

    await update.message.reply_text(
        "🆔 Telegram bilgileriniz:\n\n"
        f"ID: {user.id}\n"
        f"Kullanıcı adı: "
        f"{('@' + user.username) if user.username else 'Yok'}\n"
        f"Ad: {user.full_name}"
    )


# =========================================================
# /cekilis
# =========================================================

async def start_giveaway(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.effective_user or not update.effective_chat:
        return

    # Önce grup kontrolü
    if not is_allowed_group(update):
        await update.message.reply_text(
            "❌ Bu bot yalnızca "
            "@heroprimesohbet grubunda çalışır."
        )
        return

    user_id = update.effective_user.id

    # Admin kontrolü
    if not is_admin(user_id):
        await update.message.reply_text(
            "❌ Bu komutu yalnızca çekiliş yöneticileri "
            "kullanabilir."
        )
        return

    active = get_active_giveaway()

    if active:
        await update.message.reply_text(
            "⚠️ Zaten aktif bir çekiliş var.\n\n"
            "Önce /stopcekilis ile mevcut "
            "çekilişi bitir."
        )
        return

    if len(context.args) != 1:
        await update.message.reply_text(
            "Kullanım:\n"
            "/cekilis 10\n\n"
            "Buradaki sayı kaç kazanan seçileceğini "
            "belirtir."
        )
        return

    try:
        winner_count = int(context.args[0])

    except ValueError:
        await update.message.reply_text(
            "❌ Kazanan sayısı sayı olmalı.\n\n"
            "Örnek: /cekilis 10"
        )
        return

    if winner_count < 1:
        await update.message.reply_text(
            "❌ Kazanan sayısı en az 1 olmalı."
        )
        return

    if winner_count > 1000:
        await update.message.reply_text(
            "❌ Tek çekilişte en fazla 1000 "
            "kazanan belirleyebilirsin."
        )
        return

    initial_text = build_giveaway_text(
        winner_count,
        0,
    )

    giveaway_message = await update.message.reply_text(
        initial_text,
        parse_mode="HTML",
    )

    now = datetime.now(timezone.utc).isoformat()

    connection = get_db()

    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO giveaways (
            chat_id,
```
