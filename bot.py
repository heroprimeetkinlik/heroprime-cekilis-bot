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

# TOKEN KODUN İÇİNE YAZILMAZ.
# Railway Variables bölümüne:
# BOT_TOKEN = YENI_BOT_TOKENIN
BOT_TOKEN = '8855111211:AAFhY9oBPMEAR9jDd1WhwN2nZmFpZXMUX4s'

# Railway Variables bölümüne:
# ADMIN_IDS=8845737995
#
# Birden fazla admin:
# ADMIN_IDS=8845737995,123456789
ADMIN_IDS_RAW = "8845737995"


# =========================================================
# SADECE BU TELEGRAM GRUBUNDA ÇALIŞIR
# =========================================================

ALLOWED_GROUP_USERNAME = "heroprimesohbet"


# =========================================================
# DATABASE
# =========================================================

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

    if not update.message:
        return

    # Grup kontrolü
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
            message_id,
            started_by,
            winner_count,
            active,
            created_at
        )
        VALUES (?, ?, ?, ?, 1, ?)
        """,
        (
            update.effective_chat.id,
            giveaway_message.message_id,
            user_id,
            winner_count,
            now,
        ),
    )

    connection.commit()
    connection.close()


# =========================================================
# /katil
# =========================================================

async def join_giveaway(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.effective_user or not update.effective_chat:
        return

    if not update.message:
        return

    # Grup kontrolü
    if not is_allowed_group(update):
        return

    active = get_active_giveaway()

    if not active:
        await update.message.reply_text(
            "❌ Şu anda aktif bir çekiliş yok."
        )
        return

    # Çekiliş başka bir chat'teyse katılım engellenir.
    if active["chat_id"] != update.effective_chat.id:
        await update.message.reply_text(
            "❌ Bu grupta aktif çekiliş bulunmuyor."
        )
        return

    # Mutlaka çekiliş mesajına yanıt verilmesi gerekiyor.
    if (
        not update.message.reply_to_message
        or update.message.reply_to_message.message_id
        != active["message_id"]
    ):
        await update.message.reply_text(
            "❌ Katılmak için /katil komutunu "
            "çekiliş mesajına <b>yanıt vererek</b> "
            "kullanmalısın.\n\n"
            "Örnek:\n"
            "<code>/katil kullaniciadim</code>",
            parse_mode="HTML",
        )
        return

    if len(context.args) != 1:
        await update.message.reply_text(
            "❌ Kullanım:\n"
            "<code>/katil kullaniciadim</code>",
            parse_mode="HTML",
        )
        return

    entered_username = context.args[0].strip()

    if not entered_username:
        await update.message.reply_text(
            "❌ Kullanıcı adı boş olamaz."
        )
        return

    if entered_username.startswith("@"):
        entered_username = entered_username[1:]

    if not entered_username:
        await update.message.reply_text(
            "❌ Geçerli bir kullanıcı adı yazmalısın."
        )
        return

    user = update.effective_user

    telegram_username = (
        user.username
        if user.username
        else None
    )

    telegram_name = user.full_name or "İsimsiz kullanıcı"

    joined_at = datetime.now(timezone.utc).isoformat()

    connection = get_db()

    try:
        connection.execute(
            """
            INSERT INTO participants (
                giveaway_id,
                telegram_user_id,
                telegram_username,
                telegram_name,
                entered_username,
                joined_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                active["id"],
                user.id,
                telegram_username,
                telegram_name,
                entered_username,
                joined_at,
            ),
        )

        connection.commit()

    except sqlite3.IntegrityError:
        connection.close()

        await update.message.reply_text(
            "⚠️ Bu çekilişe zaten katıldın.\n"
            "Aynı Telegram hesabıyla ikinci kez "
            "katılamazsın."
        )
        return

    connection.close()

    # Çekiliş mesajındaki katılımcı sayısını güncelle.
    await update_giveaway_message(
        context,
        active,
    )

    await update.message.reply_text(
        f"✅ Katılımın kaydedildi.\n\n"
        f"Telegram: "
        f"{('@' + telegram_username) if telegram_username else telegram_name}\n"
        f"Site kullanıcı adı: @{entered_username}"
    )


# =========================================================
# /stopcekilis
# =========================================================

async def stop_giveaway(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.effective_user or not update.effective_chat:
        return

    if not update.message:
        return

    # Grup kontrolü
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

    if not active:
        await update.message.reply_text(
            "❌ Şu anda aktif bir çekiliş yok."
        )
        return

    if active["chat_id"] != update.effective_chat.id:
        await update.message.reply_text(
            "❌ Bu grupta aktif çekiliş bulunmuyor."
        )
        return

    connection = get_db()

    participants = connection.execute(
        """
        SELECT *
        FROM participants
        WHERE giveaway_id = ?
        ORDER BY id ASC
        """,
        (active["id"],),
    ).fetchall()

    ended_at = datetime.now(timezone.utc).isoformat()

    connection.execute(
        """
        UPDATE giveaways
        SET active = 0,
            ended_at = ?
        WHERE id = ?
        """,
        (
            ended_at,
            active["id"],
        ),
    )

    connection.commit()
    connection.close()

    if not participants:
        try:
            await context.bot.edit_message_text(
                chat_id=active["chat_id"],
                message_id=active["message_id"],
                text=(
                    "🛑 <b>ÇEKİLİŞ SONA ERDİ</b>\n\n"
                    "👥 Katılımcı: <b>0</b>\n\n"
                    "❌ Kazanan bulunamadı."
                ),
                parse_mode="HTML",
            )

        except Exception as error:
            logger.warning(
                "Çekiliş mesajı düzenlenemedi: %s",
                error,
            )

        await update.message.reply_text(
            "🛑 Çekiliş sona erdi.\n"
            "Katılımcı olmadığı için kazanan seçilmedi."
        )
        return

    participant_list = list(participants)

    winner_count = min(
        active["winner_count"],
        len(participant_list),
    )

    random_generator = secrets.SystemRandom()

    winners = random_generator.sample(
        participant_list,
        winner_count,
    )

    winner_lines = []

    for index, winner in enumerate(winners, start=1):
        telegram_identity = (
            f"@{winner['telegram_username']}"
            if winner["telegram_username"]
            else winner["telegram_name"]
        )

        winner_lines.append(
            f"{index}. "
            f"{telegram_identity} — "
            f"@{winner['entered_username']}"
        )

    winners_text = "\n".join(winner_lines)

    # Orijinal çekiliş mesajını güncelle.
    try:
        await context.bot.edit_message_text(
            chat_id=active["chat_id"],
            message_id=active["message_id"],
            text=(
                "🏁 <b>ÇEKİLİŞ SONA ERDİ!</b>\n\n"
                f"👥 Katılımcı: <b>{len(participant_list)}</b>\n"
                f"🏆 Kazanan sayısı: <b>{winner_count}</b>\n\n"
                f"<b>Kazananlar:</b>\n"
                f"{winners_text}"
            ),
            parse_mode="HTML",
        )

    except Exception as error:
        logger.warning(
            "Sonuç mesajı güncellenemedi: %s",
            error,
        )

    # Admin'e özel mesaj gönder.
    admin_message = (
        "🎉 <b>ÇEKİLİŞ SONUÇLARI</b>\n\n"
        f"👥 Toplam katılımcı: <b>{len(participant_list)}</b>\n"
        f"🏆 Kazanan sayısı: <b>{winner_count}</b>\n\n"
        f"<b>Kazananlar:</b>\n"
        f"{winners_text}"
    )

    try:
        await context.bot.send_message(
            chat_id=active["started_by"],
            text=admin_message,
            parse_mode="HTML",
        )

        dm_status = (
            "📩 Sonuçlar adminin özel mesajına gönderildi."
        )

    except Exception as error:
        logger.warning(
            "Admin özel mesajı gönderilemedi: %s",
            error,
        )

        dm_status = (
            "⚠️ Sonuçlar özel mesajla gönderilemedi. "
            "Admin botu daha önce başlatmamış olabilir."
        )

    await update.message.reply_text(
        "🛑 Çekiliş sona erdi.\n\n"
        f"👥 Katılımcı: {len(participant_list)}\n"
        f"🏆 Kazanan: {winner_count}\n\n"
        f"{dm_status}"
    )


# =========================================================
# /cekilisdurum
# =========================================================

async def giveaway_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.effective_user or not update.effective_chat:
        return

    if not update.message:
        return

    if not is_allowed_group(update):
        await update.message.reply_text(
            "❌ Bu bot yalnızca "
            "@heroprimesohbet grubunda çalışır."
        )
        return

    active = get_active_giveaway()

    if not active:
        await update.message.reply_text(
            "ℹ️ Şu anda aktif bir çekiliş yok."
        )
        return

    if active["chat_id"] != update.effective_chat.id:
        await update.message.reply_text(
            "ℹ️ Bu grupta aktif çekiliş yok."
        )
        return

    participant_count = get_participant_count(
        active["id"]
    )

    await update.message.reply_text(
        "📊 <b>ÇEKİLİŞ DURUMU</b>\n\n"
        f"🏆 Kazanan sayısı: "
        f"<b>{active['winner_count']}</b>\n"
        f"👥 Katılımcı: "
        f"<b>{participant_count}</b>\n\n"
        "🟢 Çekiliş aktif.",
        parse_mode="HTML",
    )


# =========================================================
# HATA YAKALAMA
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logger.error(
        "Telegram bot hatası:",
        exc_info=context.error,
    )


# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN Railway Variables içinde bulunamadı."
        )

    if not ADMIN_IDS:
        raise RuntimeError(
            "ADMIN_IDS Railway Variables içinde bulunamadı."
        )

    init_database()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("myid", my_id)
    )

    application.add_handler(
        CommandHandler("cekilis", start_giveaway)
    )

    application.add_handler(
        CommandHandler("katil", join_giveaway)
    )

    application.add_handler(
        CommandHandler("stopcekilis", stop_giveaway)
    )

    application.add_handler(
        CommandHandler("cekilisdurum", giveaway_status)
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "Çekiliş botu başlatılıyor..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
