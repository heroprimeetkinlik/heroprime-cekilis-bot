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

# BOT TOKEN RAILWAY VARIABLES İÇİNDEN ALINIR
BOT_TOKEN = '8855111211:AAE5iUsRRxqVmUSPVGpd5nu-Ruc2XPH7w6o'

# ADMIN ID
ADMIN_IDS_RAW = "8845737995"

# =========================================================
# ANA ÇEKİLİŞ GRUBU
# =========================================================

ALLOWED_GROUP_USERNAMES = {
    "heroprimesohbet",
    "testkanaliii00",
}

# =========================================================
# TEST / YEDEK KANAL
# =========================================================

TEST_CHANNEL_USERNAME = "@testkanaliii00"

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
# ANA GRUP KONTROLÜ
# =========================================================

def is_allowed_group(update: Update) -> bool:
    chat = update.effective_chat

    if not chat:
        return False

    if chat.type not in ("group", "supergroup"):
        return False

    username = (chat.username or "").lower()

    return username == ALLOWED_GROUP_USERNAME.lower()


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
# /START
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.effective_user or not update.message:
        return

    user = update.effective_user

    # Admin ise test kanalına üyelik zorunlu değil.
    if is_admin(user.id):

        await update.message.reply_text(
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

    # Normal kullanıcı için test kanalı kontrolü.
    is_member = await is_test_channel_member(
        context,
        user.id,
    )

    if not is_member:

        await update.message.reply_text(
            "🚀 <b>Botu kullanabilmek için test kanalına katılmalısın.</b>\n\n"
            "📢 Kanal:\n"
            "https://t.me/testkanaliii00\n\n"
            "Kanala katıldıktan sonra tekrar /start gönder.",
            parse_mode="HTML",
        )

        return

    await update.message.reply_text(
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

    if not update.effective_user or not update.message:
        return

    user = update.effective_user

    await update.message.reply_text(
        "🆔 <b>Telegram Bilgilerin</b>\n\n"
        f"ID: <code>{user.id}</code>\n"
        f"Kullanıcı adı: "
        f"{('@' + user.username) if user.username else 'Yok'}\n"
        f"Ad: {user.full_name}",
        parse_mode="HTML",
    )


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
# /CEKILIS
# =========================================================

async def start_giveaway(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.effective_user or not update.effective_chat:
        return

    if not update.message:
        return

    # SADECE ANA GRUP
    if not is_allowed_group(update):

        await update.message.reply_text(
            "❌ Bu bot yalnızca "
            "@heroprimesohbet grubunda çalışır."
        )

        return

    user_id = update.effective_user.id

    # ADMIN KONTROLÜ
    if not is_admin(user_id):

        await update.message.reply_text(
            "❌ Bu komutu yalnızca çekiliş yöneticileri "
            "kullanabilir."
        )

        return

    # AKTİF ÇEKİLİŞ KONTROLÜ
    active = get_active_giveaway()

    if active:

        await update.message.reply_text(
            "⚠️ Zaten aktif bir çekiliş var.\n\n"
            "Önce /stopcekilis ile mevcut "
            "çekilişi bitir."
        )

        return

    # KAZANAN SAYISI
    if len(context.args) != 1:

        await update.message.reply_text(
            "Kullanım:\n"
            "/cekilis 1\n\n"
            "Örneğin 1 yazarsan 1 kazanan seçilir."
        )

        return

    try:

        winner_count = int(context.args[0])

    except ValueError:

        await update.message.reply_text(
            "❌ Kazanan sayısı sayı olmalı.\n\n"
            "Örnek: /cekilis 1"
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

    # ÇEKİLİŞ MESAJI
    initial_text = build_giveaway_text(
        winner_count,
        0,
    )

    giveaway_message = await update.message.reply_text(
        initial_text,
        parse_mode="HTML",
    )

    now = datetime.now(
        timezone.utc
    ).isoformat()

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
# /KATIL
# =========================================================

async def join_giveaway(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.effective_user or not update.effective_chat:
        return

    if not update.message:
        return

    # SADECE ANA GRUP
    if not is_allowed_group(update):
        return

    active = get_active_giveaway()

    if not active:

        await update.message.reply_text(
            "❌ Şu anda aktif bir çekiliş yok."
        )

        return

    # DOĞRU GRUP
    if active["chat_id"] != update.effective_chat.id:

        await update.message.reply_text(
            "❌ Bu grupta aktif çekiliş bulunmuyor."
        )

        return

    # ÇEKİLİŞ MESAJINA YANIT KONTROLÜ
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

    # KULLANICI ADI
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

    telegram_name = (
        user.full_name
        or "İsimsiz kullanıcı"
    )

    joined_at = datetime.now(
        timezone.utc
    ).isoformat()

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

    # KATILIMCI SAYISINI GÜNCELLE
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
# /STOPCEKILIS
# =========================================================

async def stop_giveaway(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.effective_user or not update.effective_chat:
        return

    if not update.message:
        return

    # SADECE ANA GRUP
    if not is_allowed_group(update):

        await update.message.reply_text(
            "❌ Bu bot yalnızca "
            "@heroprimesohbet grubunda çalışır."
        )

        return

    user_id = update.effective_user.id

    # ADMIN
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

    ended_at = datetime.now(
        timezone.utc
    ).isoformat()

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

    # KATILIMCI YOKSA
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

    # KAZANANLAR
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

    for index, winner in enumerate(
        winners,
        start=1,
    ):

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

    winners_text = "\n".join(
        winner_lines
    )

    # =====================================================
    # GRUPTA SONUÇ MESAJINI GÜNCELLE
    # =====================================================

    try:

        await context.bot.edit_message_text(
            chat_id=active["chat_id"],
            message_id=active["message_id"],
            text=(
                "🏁 <b>ÇEKİLİŞ SONA ERDİ!</b>\n\n"
                f"👥 Katılımcı: "
                f"<b>{len(participant_list)}</b>\n"
                f"🏆 Kazanan sayısı: "
                f"<b>{winner_count}</b>\n\n"
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

    # =====================================================
    # ADMIN'E ÖZEL MESAJ
    # =====================================================

    admin_message = (
        "🎉 <b>ÇEKİLİŞ SONUÇLARI</b>\n\n"
        f"👥 Toplam katılımcı: "
        f"<b>{len(participant_list)}</b>\n"
        f"🏆 Kazanan sayısı: "
        f"<b>{winner_count}</b>\n\n"
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

    # =====================================================
    # GRUPTA BİLGİ
    # =====================================================

    await update.message.reply_text(
        "🛑 Çekiliş sona erdi.\n\n"
        f"👥 Katılımcı: {len(participant_list)}\n"
        f"🏆 Kazanan: {winner_count}\n\n"
        f"{dm_status}"
    )


# =========================================================
# /CEKILISDURUM
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
            "ADMIN ID bulunamadı."
        )

    init_database()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # /start
    application.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    # /myid
    application.add_handler(
        CommandHandler(
            "myid",
            my_id,
        )
    )

    # /cekilis
    application.add_handler(
        CommandHandler(
            "cekilis",
            start_giveaway,
        )
    )

    # /katil
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
        "Çekiliş botu başlatılıyor..."
    )

    logger.info(
        "Ana grup: @%s",
        ALLOWED_GROUP_USERNAME,
    )

    logger.info(
        "Test kanalı: %s",
        TEST_CHANNEL_USERNAME,
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# =========================================================
# BAŞLAT
# =========================================================

if __name__ == "__main__":
    main()
