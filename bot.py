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

# BOT TOKEN KESİNLİKLE KODUN İÇİNE YAZILMAZ.
# Railway Variables üzerinden alınır.
BOT_TOKEN = '8855111211:AAFhY9oBPMEAR9jDd1WhwN2nZmFpZXMUX4s'

# Railway Variables:
# ADMIN_IDS=8845737995
#
# Birden fazla admin için:
# ADMIN_IDS=8845737995,123456789
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()

# Railway Volume kullanırsan DB_FILE'i volume yoluna
# çevirebilirsin. Şimdilik varsayılan:
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

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "❌ Bu komutu yalnızca çekiliş yöneticileri "
            "kullanabilir."
        )
        return

    if update.effective_chat.type not in (
        "group",
        "supergroup",
    ):
        await update.message.reply_text(
            "❌ Çekiliş yalnızca grup içinde "
            "başlatılabilir."
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

    await update.message.reply_text(
        "✅ Çekiliş başlatıldı.\n\n"
        f"🏆 Kazanan sayısı: {winner_count}\n"
        "👥 Katılımcılar çekiliş mesajına "
        "yanıt vererek /katil kullanıcı_adı "
        "yazabilir."
    )


# =========================================================
# /katil
# =========================================================

async def join_giveaway(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.effective_user or not update.message:
        return

    active = get_active_giveaway()

    if not active:
        await update.message.reply_text(
            "❌ Şu anda aktif bir çekiliş "
            "bulunmuyor."
        )
        return

    # Katılım mesajı mutlaka aktif çekiliş
    # mesajına reply olmalı.
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ Çekilişe katılmak için "
            "çekiliş mesajını yanıtlayarak "
            "/katil kullanıcı_adınız yazmalısın."
        )
        return

    replied_message_id = (
        update.message.reply_to_message.message_id
    )

    if replied_message_id != active["message_id"]:
        await update.message.reply_text(
            "❌ Bu mesaj aktif çekiliş mesajı değil.\n\n"
            "Lütfen aktif çekiliş mesajını yanıtla."
        )
        return

    if len(context.args) != 1:
        await update.message.reply_text(
            "❌ Kullanım:\n"
            "/katil kullanıcı_adınız\n\n"
            "Örnek:\n"
            "/katil ahmet123"
        )
        return

    entered_username = context.args[0].strip()

    if entered_username.startswith("@"):
        entered_username = entered_username[1:]

    if not entered_username:
        await update.message.reply_text(
            "❌ Geçerli bir kullanıcı adı "
            "yazmalısın."
        )
        return

    user = update.effective_user

    telegram_username = (
        f"@{user.username}"
        if user.username
        else None
    )

    telegram_name = user.full_name.strip()

    now = datetime.now(timezone.utc).isoformat()

    connection = get_db()

    try:
        cursor = connection.cursor()

        cursor.execute(
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
                now,
            ),
        )

        connection.commit()

    except sqlite3.IntegrityError:
        await update.message.reply_text(
            "⚠️ Bu çekilişe zaten katıldın."
        )
        return

    finally:
        connection.close()

    # Katılımcı sayısını güncelle.
    active = get_active_giveaway()

    if active:
        await update_giveaway_message(
            context,
            active,
        )

    await update.message.reply_text(
        "✅ Çekilişe katılımın kaydedildi.\n\n"
        f"👤 Telegram: "
        f"{telegram_username or telegram_name}\n"
        f"📝 Kullanıcı adı: {entered_username}"
    )


# =========================================================
# /stopcekilis
# =========================================================

async def stop_giveaway(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "❌ Bu komutu yalnızca çekiliş yöneticileri "
            "kullanabilir."
        )
        return

    active = get_active_giveaway()

    if not active:
        await update.message.reply_text(
            "❌ Aktif çekiliş bulunmuyor."
        )
        return

    connection = get_db()

    participants = connection.execute(
        """
        SELECT *
        FROM participants
        WHERE giveaway_id = ?
        """,
        (active["id"],),
    ).fetchall()

    now = datetime.now(timezone.utc).isoformat()

    connection.execute(
        """
        UPDATE giveaways
        SET active = 0,
            ended_at = ?
        WHERE id = ?
        """,
        (
            now,
            active["id"],
        ),
    )

    connection.commit()
    connection.close()

    participant_list = list(participants)

    # -----------------------------------------------------
    # KATILIMCI YOKSA
    # -----------------------------------------------------

    if not participant_list:
        try:
            await context.bot.edit_message_text(
                chat_id=active["chat_id"],
                message_id=active["message_id"],
                text=(
                    "🛑 <b>ÇEKİLİŞ SONA ERDİ!</b>\n\n"
                    "👥 Katılımcı: <b>0</b>\n\n"
                    "❌ Katılımcı olmadığı için "
                    "kazanan seçilemedi."
                ),
                parse_mode="HTML",
            )

        except Exception:
            pass

        await update.message.reply_text(
            "🛑 Çekiliş sonlandırıldı.\n"
            "Katılımcı olmadığı için kazanan yok."
        )

        return

    # -----------------------------------------------------
    # KAZANANLARI SEÇ
    # -----------------------------------------------------

    winner_count = min(
        active["winner_count"],
        len(participant_list),
    )

    rng = secrets.SystemRandom()

    winners = rng.sample(
        participant_list,
        winner_count,
    )

    # -----------------------------------------------------
    # GRUP MESAJINI SONUÇ OLARAK GÜNCELLE
    # -----------------------------------------------------

    result_lines = [
        "🎉 <b>ÇEKİLİŞ SONA ERDİ!</b>",
        "",
        f"👥 Toplam katılımcı: "
        f"<b>{len(participant_list)}</b>",
        f"🏆 Kazanan sayısı: "
        f"<b>{len(winners)}</b>",
        "",
        "<b>Kazananlar:</b>",
    ]

    for index, winner in enumerate(
        winners,
        start=1,
    ):
        if winner["telegram_username"]:
            telegram_display = (
                winner["telegram_username"]
            )
        else:
            telegram_display = (
                winner["telegram_name"]
            )

        result_lines.append(
            f"{index}. {telegram_display} — "
            f"<code>{winner['entered_username']}</code>"
        )

    result_text = "\n".join(result_lines)

    try:
        await context.bot.edit_message_text(
            chat_id=active["chat_id"],
            message_id=active["message_id"],
            text=result_text,
            parse_mode="HTML",
        )

    except Exception as error:
        logger.warning(
            "Sonuç mesajı güncellenemedi: %s",
            error,
        )

    # -----------------------------------------------------
    # ÇEKİLİŞİ BAŞLATAN ADMİNE ÖZEL MESAJ
    # -----------------------------------------------------

    dm_lines = [
        "🎉 ÇEKİLİŞ SONUÇLARI",
        "",
        f"👥 Toplam katılımcı: "
        f"{len(participant_list)}",
        f"🏆 Kazanan sayısı: "
        f"{len(winners)}",
        "",
        "Kazananlar:",
        "",
    ]

    for index, winner in enumerate(
        winners,
        start=1,
    ):
        telegram_display = (
            winner["telegram_username"]
            or winner["telegram_name"]
        )

        dm_lines.append(
            f"{index}. Telegram: "
            f"{telegram_display}\n"
            f"   Kullanıcı adı: "
            f"{winner['entered_username']}"
        )

    dm_text = "\n".join(dm_lines)

    try:
        await context.bot.send_message(
            chat_id=active["started_by"],
            text=dm_text,
        )

        dm_sent = True

    except Exception as error:
        logger.warning(
            "Admin özel mesajı gönderilemedi: %s",
            error,
        )

        dm_sent = False

    # -----------------------------------------------------
    # ADMİNE BİLGİ
    # -----------------------------------------------------

    message = (
        "🛑 Çekiliş sona erdi.\n\n"
        f"👥 Katılımcı: "
        f"{len(participant_list)}\n"
        f"🏆 Seçilen kazanan: "
        f"{len(winners)}\n"
    )

    if dm_sent:
        message += (
            "\n📩 Kazanan bilgileri çekilişi "
            "başlatan adminin özel mesajına "
            "gönderildi."
        )

    else:
        message += (
            "\n⚠️ Özel mesaj gönderilemedi. "
            "Botu önce Telegram'da başlatıp "
            "mesaj göndermesine izin ver."
        )

    await update.message.reply_text(message)


# =========================================================
# /cekilisdurum
# =========================================================

async def giveaway_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    active = get_active_giveaway()

    if not active:
        await update.message.reply_text(
            "ℹ️ Şu anda aktif çekiliş yok."
        )
        return

    participant_count = get_participant_count(
        active["id"]
    )

    await update.message.reply_text(
        "🟢 AKTİF ÇEKİLİŞ\n\n"
        f"🏆 Kazanan sayısı: "
        f"{active['winner_count']}\n"
        f"👥 Katılımcı: "
        f"{participant_count}\n\n"
        "Katılım için aktif çekiliş mesajına "
        "yanıt vererek /katil kullanıcı_adı yazın."
    )


# =========================================================
# HATA YÖNETİMİ
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
            "BOT_TOKEN bulunamadı. "
            "Railway Variables kısmına "
            "BOT_TOKEN ekle."
        )

    if not ADMIN_IDS:
        raise RuntimeError(
            "ADMIN_IDS bulunamadı veya geçersiz. "
            "Railway Variables kısmına "
            "ADMIN_IDS=8845737995 şeklinde ekle."
        )

    init_database()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # /myid
    application.add_handler(
        CommandHandler(
            "myid",
            my_id,
        )
    )

    # /cekilis 10
    application.add_handler(
        CommandHandler(
            "cekilis",
            start_giveaway,
        )
    )

    # /katil kullaniciadi
    application.add_handler(
        CommandHandler(
            "katil",
            join_giveaway,
        )
    )

    # /stopcekilis
    application.add_handler(
        CommandHandler(
            "stopcekilis",
            stop_giveaway,
        )
    )

    # /cekilisdurum
    application.add_handler(
        CommandHandler(
            "cekilisdurum",
            giveaway_status,
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "🎁 Çekiliş botu çalışıyor..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
```
