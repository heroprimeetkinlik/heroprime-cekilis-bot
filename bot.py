import os
import sqlite3
import secrets
import logging
from datetime import datetime, timezone
from html import escape

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# =========================================================
# AYARLAR
# =========================================================

# Railway > Variables bölümüne BOT_TOKEN ekle.
BOT_TOKEN = '8855111211:AAE5iUsRRxqVmUSPVGpd5nu-Ruc2XPH7w6o'

# Admin Telegram ID
ADMIN_IDS_RAW = "8845737995"

# Kazanan sonuçlarının gönderileceği admin hesabı
ADMIN_RESULT_CHAT_ID = 8845737995
ADMIN_RESULT_USERNAME = "@HeroPrimeMarketing"

# İzinli çekiliş sohbetleri
ALLOWED_CHAT_USERNAMES = {
    "heroprimesohbet",
    "testkanaliii00",
}

TEST_CHANNEL_USERNAME = "@testkanaliii00"

# Veritabanı
DB_FILE = os.getenv("DB_FILE", "giveaway.db")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# =========================================================
# YARDIMCI FONKSİYONLAR
# =========================================================

def get_admin_ids():
    admin_ids = set()

    for value in ADMIN_IDS_RAW.split(","):
        value = value.strip()
        if not value:
            continue

        try:
            admin_ids.add(int(value))
        except ValueError:
            logger.warning("Geçersiz ADMIN_IDS değeri: %s", value)

    return admin_ids


ADMIN_IDS = get_admin_ids()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def normalize_username(username: str) -> str:
    return username.strip().lstrip("@").lower()


def is_allowed_chat(update: Update) -> bool:
    chat = update.effective_chat

    if not chat:
        return False

    if chat.type not in ("group", "supergroup", "channel"):
        return False

    username = normalize_username(chat.username or "")

    return username in {
        normalize_username(name)
        for name in ALLOWED_CHAT_USERNAMES
    }


def allowed_chat_text() -> str:
    return "@heroprimesohbet veya @testkanaliii00"


def get_db():
    connection = sqlite3.connect(DB_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# =========================================================
# TEST KANALI ÜYELİK KONTROLÜ
# =========================================================

async def is_test_channel_member(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
) -> bool:
    try:
        member = await context.bot.get_chat_member(
            chat_id=TEST_CHANNEL_USERNAME,
            user_id=user_id,
        )

        return member.status in (
            "member",
            "administrator",
            "creator",
        )

    except Exception as error:
        logger.warning(
            "Test kanalı üyelik kontrolü başarısız: %s",
            error,
        )
        return False


# =========================================================
# DATABASE
# =========================================================

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
            FOREIGN KEY(giveaway_id) REFERENCES giveaways(id)
        )
        """
    )

    connection.commit()
    connection.close()


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
# ÇEKİLİŞ MESAJLARI
# =========================================================

def build_giveaway_text(winner_count: int, participant_count: int) -> str:
    return (
        "🎉 <b>HEROPRIME ÇEKİLİŞ BAŞLADI!</b>\n\n"
        "🎁 Çekilişe katılmak için bu mesaja yanıt vererek:\n"
        "<code>/katil kullanıcı_adınız</code>\n"
        "yazın.\n\n"
        f"🏆 Kazanan sayısı: <b>{winner_count}</b>\n"
        f"👥 Katılımcı: <b>{participant_count}</b>\n\n"
        "🍀 <b>Herkese bol şans!</b>"
    )


def build_finished_text(
    participant_count: int,
    winner_count: int,
    winners_text: str,
) -> str:
    return (
        "🏁 <b>HEROPRIME ÇEKİLİŞ SONA ERDİ!</b>\n\n"
        f"👥 Toplam katılımcı: <b>{participant_count}</b>\n"
        f"🏆 Kazanan sayısı: <b>{winner_count}</b>\n\n"
        "<b>🎉 KAZANANLAR</b>\n"
        f"{winners_text}\n\n"
        "🍀 <b>Tüm katılımcılara teşekkürler!</b>"
    )


async def update_giveaway_message(
    context: ContextTypes.DEFAULT_TYPE,
    giveaway,
):
    participant_count = get_participant_count(giveaway["id"])

    try:
        await context.bot.edit_message_text(
            chat_id=giveaway["chat_id"],
            message_id=giveaway["message_id"],
            text=build_giveaway_text(
                giveaway["winner_count"],
                participant_count,
            ),
            parse_mode="HTML",
        )
    except Exception as error:
        logger.warning(
            "Çekiliş mesajı güncellenemedi: %s",
            error,
        )


# =========================================================
# /START
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    user = update.effective_user

    if not user or not message:
        return

    # Admin özelden /start yaptığında teknik bilgi mesajı gönderilir.
    # Bu mesaj gruplarda otomatik olarak gönderilmez.
    if is_admin(user.id):
        await message.reply_text(
            "🤖 <b>Çekiliş Botu aktif.</b>\n\n"
            "👤 Admin erişimi doğrulandı.\n"
            "🟢 Ana çekiliş grubu: @heroprimesohbet\n"
            "🧪 Test kanalı: @testkanaliii00\n\n"
            "Komutlar:\n"
            "/myid - Telegram ID bilgileri\n"
            "/cekilis 1 - Çekiliş başlat\n"
            "/cekilisdurum - Çekiliş durumu\n"
            "/stopcekilis - Çekilişi bitir",
            parse_mode="HTML",
        )
        return

    is_member = await is_test_channel_member(context, user.id)

    if not is_member:
        await message.reply_text(
            "🚀 <b>Botu kullanabilmek için test kanalına katılmalısın.</b>\n\n"
            "📢 Kanal:\n"
            "https://t.me/testkanaliii00\n\n"
            "Kanala katıldıktan sonra tekrar /start gönder.",
            parse_mode="HTML",
        )
        return

    await message.reply_text(
        "✅ <b>Hoş geldin!</b>\n\n"
        "Bot kullanımına erişimin açık.\n\n"
        "🆔 Telegram ID'ni görmek için:\n"
        "/myid",
        parse_mode="HTML",
    )


# =========================================================
# /MYID
# =========================================================

async def my_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    user = update.effective_user

    if not user or not message:
        return

    username = f"@{user.username}" if user.username else "Yok"

    await message.reply_text(
        "🆔 <b>Telegram Bilgilerin</b>\n\n"
        f"ID: <code>{user.id}</code>\n"
        f"Kullanıcı adı: {escape(username)}\n"
        f"Ad: {escape(user.full_name)}",
        parse_mode="HTML",
    )


# =========================================================
# /CEKILIS
# =========================================================

async def start_giveaway(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not user or not chat or not message:
        return

    if not is_allowed_chat(update):
        await message.reply_text(
            f"❌ Bu bot yalnızca {allowed_chat_text()} sohbetlerinde çalışır."
        )
        return

    if not is_admin(user.id):
        await message.reply_text(
            "❌ Bu komutu yalnızca çekiliş yöneticisi kullanabilir."
        )
        return

    active = get_active_giveaway()

    if active:
        await message.reply_text(
            "⚠️ Zaten aktif bir çekiliş var.\n\n"
            "Önce /stopcekilis ile mevcut çekilişi bitir."
        )
        return

    if len(context.args) != 1:
        await message.reply_text(
            "❌ Kullanım: /cekilis 1\n\n"
            "Sayı kazanan sayısını belirler. "
            "Katılımcı sayısında sınır yoktur."
        )
        return

    try:
        winner_count = int(context.args[0])
    except ValueError:
        await message.reply_text(
            "❌ Kazanan sayısı sayı olmalı.\n\n"
            "Örnek: /cekilis 1"
        )
        return

    if winner_count < 1:
        await message.reply_text(
            "❌ Kazanan sayısı en az 1 olmalı."
        )
        return

    # Önce mesajı gönderiyoruz.
    # Kullanıcılar bu mesaja yanıt vererek katılacak.
    try:
        giveaway_message = await message.reply_text(
            build_giveaway_text(winner_count, 0),
            parse_mode="HTML",
        )
    except Exception as error:
        logger.exception(
            "Çekiliş mesajı gönderilemedi: %s",
            error,
        )
        return

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
            chat.id,
            giveaway_message.message_id,
            user.id,
            winner_count,
            utc_now(),
        ),
    )

    connection.commit()
    connection.close()

    logger.info(
        "Çekiliş başlatıldı: giveaway_id=%s chat_id=%s winner_count=%s",
        cursor.lastrowid,
        chat.id,
        winner_count,
    )


# =========================================================
# /KATIL
# =========================================================

async def join_giveaway(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not user or not chat or not message:
        return

    if not is_allowed_chat(update):
        return

    active = get_active_giveaway()

    if not active:
        await message.reply_text("❌ Şu anda aktif bir çekiliş yok.")
        return

    if active["chat_id"] != chat.id:
        await message.reply_text(
            "❌ Bu sohbette aktif çekiliş bulunmuyor."
        )
        return

    # /katil, çekiliş mesajına yanıt olarak kullanılmalı.
    reply_to = message.reply_to_message

    if not reply_to or reply_to.message_id != active["message_id"]:
        await message.reply_text(
            "❌ Katılmak için /katil komutunu çekiliş mesajına "
            "yanıt vererek kullanmalısın.\n\n"
            "Örnek:\n"
            "<code>/katil kullaniciadim</code>",
            parse_mode="HTML",
        )
        return

    if len(context.args) != 1:
        await message.reply_text(
            "❌ Kullanım:\n"
            "<code>/katil kullaniciadim</code>",
            parse_mode="HTML",
        )
        return

    entered_username = context.args[0].strip().lstrip("@")

    if not entered_username:
        await message.reply_text(
            "❌ Geçerli bir kullanıcı adı yazmalısın."
        )
        return

    telegram_username = user.username or None
    telegram_name = user.full_name or "İsimsiz kullanıcı"

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
                utc_now(),
            ),
        )

        connection.commit()

    except sqlite3.IntegrityError:
        connection.close()

        await message.reply_text(
            "⚠️ Bu çekilişe zaten katıldın.\n"
            "Aynı Telegram hesabıyla ikinci kez katılamazsın."
        )
        return

    connection.close()

    # Katılım sayısını ana çekiliş mesajına yansıt.
    await update_giveaway_message(context, active)

    # Katılım grupta gösterilmez; kullanıcıya özelden bildirim gönderilir.
    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=(
                "✅ <b>Çekilişe katılımın başarıyla kaydedildi!</b>\n\n"
                f"👤 Telegram: {escape(telegram_name)}\n"
                f"🎟 Kullanıcı adı: @{escape(entered_username)}\n\n"
                "🍀 Bol şans!"
            ),
            parse_mode="HTML",
        )
    except Exception as error:
        logger.warning(
            "Katılım başarı mesajı kullanıcıya özelden gönderilemedi: %s",
            error,
        )


# =========================================================
# /STOPCEKILIS
# =========================================================

async def stop_giveaway(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not user or not chat or not message:
        return

    if not is_allowed_chat(update):
        await message.reply_text(
            f"❌ Bu bot yalnızca {allowed_chat_text()} sohbetlerinde çalışır."
        )
        return

    if not is_admin(user.id):
        await message.reply_text(
            "❌ Bu komutu yalnızca çekiliş yöneticisi kullanabilir."
        )
        return

    active = get_active_giveaway()

    if not active:
        await message.reply_text(
            "❌ Şu anda aktif bir çekiliş yok."
        )
        return

    if active["chat_id"] != chat.id:
        await message.reply_text(
            "❌ Bu sohbette aktif çekiliş bulunmuyor."
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

    connection.execute(
        """
        UPDATE giveaways
        SET active = 0,
            ended_at = ?
        WHERE id = ?
        """,
        (utc_now(), active["id"]),
    )

    connection.commit()
    connection.close()

    participant_list = list(participants)
    participant_count = len(participant_list)

    # =====================================================
    # KATILIMCI YOK
    # =====================================================

    if not participant_list:
        no_winner_text = (
            "🏁 <b>HEROPRIME ÇEKİLİŞ SONA ERDİ!</b>\n\n"
            "👥 Toplam katılımcı: <b>0</b>\n\n"
            "❌ Bu çekilişte kazanan bulunamadı.\n\n"
            "🍀 Bir sonraki çekilişte bol şans!"
        )

        try:
            await context.bot.edit_message_text(
                chat_id=active["chat_id"],
                message_id=active["message_id"],
                text=no_winner_text,
                parse_mode="HTML",
            )
        except Exception as error:
            logger.warning(
                "Çekiliş bitiş mesajı güncellenemedi: %s",
                error,
            )

        try:
            await context.bot.send_message(
                chat_id=ADMIN_RESULT_CHAT_ID,
                text=(
                    "🏁 <b>HEROPRIME ÇEKİLİŞ SONUCU</b>\n\n"
                    "👥 Toplam katılımcı: <b>0</b>\n"
                    "❌ Kazanan bulunamadı."
                ),
                parse_mode="HTML",
            )
            dm_status = "📩 Sonuçlar özelden sana gönderildi."

        except Exception as error:
            logger.warning(
                "Admin özel mesajı gönderilemedi: %s",
                error,
            )
            dm_status = (
                "⚠️ Özel mesaj gönderilemedi. "
                "Botla özelden /start yapılmış olmalı."
            )

        await message.reply_text(
            "🛑 <b>Çekiliş sonlandırıldı.</b>\n\n"
            f"👥 Katılımcı: <b>0</b>\n"
            "❌ Kazanan yok.\n\n"
            f"{dm_status}",
            parse_mode="HTML",
        )
        return

    # =====================================================
    # KAZANANLAR
    # =====================================================

    winner_count = min(
        active["winner_count"],
        participant_count,
    )

    winners = secrets.SystemRandom().sample(
        participant_list,
        winner_count,
    )

    group_lines = []
    admin_lines = []

    for index, winner in enumerate(winners, start=1):
        telegram_username = winner["telegram_username"]

        if telegram_username:
            telegram_identity = f"@{telegram_username}"
        else:
            telegram_identity = winner["telegram_name"]

        entered_username = winner["entered_username"]

        group_lines.append(
            f"{index}. {escape(telegram_identity)} "
            f"— @{escape(entered_username)}"
        )

        admin_lines.append(
            f"{index}. <b>{escape(telegram_identity)}</b>\n"
            f"   🆔 Telegram ID: <code>{winner['telegram_user_id']}</code>\n"
            f"   🎟 Katılım kullanıcı adı: @{escape(entered_username)}"
        )

    winners_text_group = "\n".join(group_lines)
    winners_text_admin = "\n\n".join(admin_lines)

    # =====================================================
    # GRUPTA SONUÇ
    # =====================================================

    finished_text = build_finished_text(
        participant_count,
        winner_count,
        winners_text_group,
    )

    try:
        await context.bot.edit_message_text(
            chat_id=active["chat_id"],
            message_id=active["message_id"],
            text=finished_text,
            parse_mode="HTML",
        )
    except Exception as error:
        logger.warning(
            "Sonuç mesajı güncellenemedi: %s",
            error,
        )

    # Ek olarak stop komutunun altına kısa özet.
    try:
        await message.reply_text(
            "🏁 <b>Çekiliş sonlandırıldı!</b>\n\n"
            f"👥 Toplam katılımcı: <b>{participant_count}</b>\n"
            f"🏆 Kazanan: <b>{winner_count}</b>\n\n"
            "📩 Kazanan bilgileri sana özelden gönderildi.",
            parse_mode="HTML",
        )
    except Exception as error:
        logger.warning(
            "Grup sonuç özeti gönderilemedi: %s",
            error,
        )

    # =====================================================
    # ADMİNE ÖZELDEN SONUÇ
    # =====================================================

    admin_message = (
        "🎉 <b>HEROPRIME ÇEKİLİŞ SONUÇLARI</b>\n\n"
        f"👥 Toplam katılımcı: <b>{participant_count}</b>\n"
        f"🏆 Kazanan sayısı: <b>{winner_count}</b>\n\n"
        "<b>🏆 KAZANANLAR</b>\n\n"
        f"{winners_text_admin}"
    )

    try:
        await context.bot.send_message(
            chat_id=ADMIN_RESULT_CHAT_ID,
            text=admin_message,
            parse_mode="HTML",
        )

    except Exception as error:
        logger.warning(
            "Admin özel mesajı gönderilemedi: %s",
            error,
        )


# =========================================================
# /CEKILISDURUM
# =========================================================

async def giveaway_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    chat = update.effective_chat

    if not chat or not message:
        return

    if not is_allowed_chat(update):
        await message.reply_text(
            f"❌ Bu bot yalnızca {allowed_chat_text()} sohbetlerinde çalışır."
        )
        return

    active = get_active_giveaway()

    if not active:
        await message.reply_text(
            "ℹ️ Şu anda aktif bir çekiliş yok."
        )
        return

    if active["chat_id"] != chat.id:
        await message.reply_text(
            "ℹ️ Bu sohbette aktif çekiliş yok."
        )
        return

    participant_count = get_participant_count(active["id"])

    await message.reply_text(
        "📊 <b>ÇEKİLİŞ DURUMU</b>\n\n"
        f"🏆 Kazanan sayısı: <b>{active['winner_count']}</b>\n"
        f"👥 Katılımcı: <b>{participant_count}</b>\n\n"
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
            "Admin ID bulunamadı."
        )

    init_database()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start_command)
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

    application.add_error_handler(error_handler)

    logger.info("Çekiliş botu başlatılıyor...")
    logger.info(
        "İzin verilen sohbetler: %s",
        ", ".join(
            f"@{name}" for name in sorted(ALLOWED_CHAT_USERNAMES)
        ),
    )
    logger.info(
        "Admin sonuç hesabı: %s",
        ADMIN_RESULT_USERNAME,
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
