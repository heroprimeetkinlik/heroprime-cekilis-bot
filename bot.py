import os
import sqlite3
import secrets
import logging
from datetime import datetime, timezone
from html import escape

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# =========================================================
# AYARLAR
# =========================================================

# Railway > Variables bölümüne BOT_TOKEN ekle.
BOT_TOKEN = '8855111211:AAE5iUsRRxqVmUSPVGpd5nu-Ruc2XPH7w6o'

# Admin Telegram ID
ADMIN_IDS_RAW = "8845737995"

# Sonuçların gönderileceği admin hesabı
ADMIN_RESULT_CHAT_ID = 8845737995
ADMIN_RESULT_USERNAME = "@HeroPrimeMarketing"

# İzin verilen çekiliş sohbetleri
ALLOWED_CHAT_USERNAMES = {
    "heroprimesohbet",
    "testkanaliii00",
}

# Test kanalı
TEST_CHANNEL_USERNAME = "@testkanaliii00"

# Veritabanı
DB_FILE = os.getenv("DB_FILE", "giveaway.db")

# Callback prefix
JOIN_CALLBACK_PREFIX = "giveaway_join:"

# Varsayılan çekiliş metni
DEFAULT_GIVEAWAY_TEXT = (
    "🎉 <b>HEROPRIME ÇEKİLİŞ BAŞLADI!</b>\n\n"
    "🎟️ Çekilişe katılmak için aşağıdaki "
    "<b>KATIL</b> butonuna bas.\n\n"
    "🍀 <b>Herkese bol şans!</b>"
)


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# ADMİNLER
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
            logger.warning(
                "Geçersiz ADMIN_IDS değeri: %s",
                value,
            )

    return admin_ids


ADMIN_IDS = get_admin_ids()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# =========================================================
# YARDIMCI FONKSİYONLAR
# =========================================================

def normalize_username(username: str) -> str:
    return username.strip().lstrip("@").lower()


def is_allowed_chat(update: Update) -> bool:
    chat = update.effective_chat

    if not chat:
        return False

    if chat.type not in ("group", "supergroup", "channel"):
        return False

    username = normalize_username(chat.username or "")

    allowed = {
        normalize_username(name)
        for name in ALLOWED_CHAT_USERNAMES
    }

    return username in allowed


def allowed_chat_text() -> str:
    return "@heroprimesohbet veya @testkanaliii00"


def get_db():
    connection = sqlite3.connect(
        DB_FILE,
        timeout=30,
    )

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

    # Çekilişler
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

    # Katılımcılar
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

    # Bot ayarları
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    # Varsayılan metni ilk çalıştırmada kaydet
    cursor.execute(
        """
        SELECT setting_value
        FROM bot_settings
        WHERE setting_key = ?
        """,
        ("giveaway_text",),
    )

    row = cursor.fetchone()

    if row is None:
        cursor.execute(
            """
            INSERT INTO bot_settings (
                setting_key,
                setting_value,
                updated_at
            )
            VALUES (?, ?, ?)
            """,
            (
                "giveaway_text",
                DEFAULT_GIVEAWAY_TEXT,
                utc_now(),
            ),
        )

    connection.commit()
    connection.close()

    logger.info("Database hazır.")


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


def get_giveaway_text() -> str:
    connection = get_db()

    row = connection.execute(
        """
        SELECT setting_value
        FROM bot_settings
        WHERE setting_key = ?
        """,
        ("giveaway_text",),
    ).fetchone()

    connection.close()

    if row and row["setting_value"]:
        return row["setting_value"]

    return DEFAULT_GIVEAWAY_TEXT


def save_giveaway_text(new_text: str):
    connection = get_db()

    connection.execute(
        """
        INSERT INTO bot_settings (
            setting_key,
            setting_value,
            updated_at
        )
        VALUES (?, ?, ?)

        ON CONFLICT(setting_key)
        DO UPDATE SET
            setting_value = excluded.setting_value,
            updated_at = excluded.updated_at
        """,
        (
            "giveaway_text",
            new_text,
            utc_now(),
        ),
    )

    connection.commit()
    connection.close()


# =========================================================
# ÇEKİLİŞ METİNLERİ
# =========================================================

def build_giveaway_text(
    custom_text: str,
    winner_count: int,
    participant_count: int,
) -> str:

    return (
        f"{custom_text}\n\n"
        f"🏆 Kazanan sayısı: <b>{winner_count}</b>\n"
        f"👥 Katılımcı: <b>{participant_count}</b>"
    )


def build_finished_text(
    custom_text: str,
    participant_count: int,
    winner_count: int,
    winners_text: str,
) -> str:

    return (
        "🏁 <b>HEROPRIME ÇEKİLİŞ SONA ERDİ!</b>\n\n"
        f"{custom_text}\n\n"
        f"👥 Toplam katılımcı: <b>{participant_count}</b>\n"
        f"🏆 Kazanan sayısı: <b>{winner_count}</b>\n\n"
        "<b>🎉 KAZANANLAR</b>\n\n"
        f"{winners_text}\n\n"
        "🍀 <b>Tüm katılımcılara teşekkürler!</b>"
    )


def build_join_keyboard(giveaway_id: int):
    keyboard = [
        [
            InlineKeyboardButton(
                "🎟️ KATIL",
                callback_data=f"{JOIN_CALLBACK_PREFIX}{giveaway_id}",
            )
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# ÇEKİLİŞ MESAJINI GÜNCELLE
# =========================================================

async def update_giveaway_message(
    context: ContextTypes.DEFAULT_TYPE,
    giveaway,
):
    participant_count = get_participant_count(
        giveaway["id"]
    )

    custom_text = get_giveaway_text()

    text = build_giveaway_text(
        custom_text,
        giveaway["winner_count"],
        participant_count,
    )

    try:
        await context.bot.edit_message_text(
            chat_id=giveaway["chat_id"],
            message_id=giveaway["message_id"],
            text=text,
            parse_mode="HTML",
            reply_markup=build_join_keyboard(
                giveaway["id"]
            ),
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

    # Admin özel mesaj
    if is_admin(user.id) and message.chat.type == "private":
        await message.reply_text(
            "🤖 <b>HEROPRIME Çekiliş Botu aktif.</b>\n\n"
            "👤 Admin erişimi doğrulandı.\n\n"
            "Komutlar:\n"
            "/myid\n"
            "/cekilismet\n"
            "/cekilis 3\n"
            "/cekilisdurum\n"
            "/stopcekilis",
            parse_mode="HTML",
        )
        return

    # Grup / normal kullanıcı
    if message.chat.type == "private":
        is_member = await is_test_channel_member(
            context,
            user.id,
        )

        if not is_member:
            await message.reply_text(
                "🚀 <b>Botu kullanabilmek için "
                "test kanalına katılmalısın.</b>\n\n"
                "📢 Kanal:\n"
                "https://t.me/testkanaliii00\n\n"
                "Kanala katıldıktan sonra tekrar "
                "/start gönder.",
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

    username = (
        f"@{user.username}"
        if user.username
        else "Yok"
    )

    await message.reply_text(
        "🆔 <b>Telegram Bilgilerin</b>\n\n"
        f"ID: <code>{user.id}</code>\n"
        f"Kullanıcı adı: {escape(username)}\n"
        f"Ad: {escape(user.full_name)}",
        parse_mode="HTML",
    )


# =========================================================
# /CEKILISMET
# =========================================================

async def giveaway_text_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    user = update.effective_user

    if not user or not message:
        return

    # Sadece admin + özel mesaj
    if not is_admin(user.id):
        await message.reply_text(
            "❌ Bu komutu yalnızca çekiliş yöneticisi kullanabilir."
        )
        return

    if message.chat.type != "private":
        await message.reply_text(
            "🔒 /cekilismet komutu yalnızca "
            "botla özel mesajda kullanılabilir."
        )
        return

    current_text = get_giveaway_text()

    context.user_data["waiting_for_giveaway_text"] = True

    await message.reply_text(
        "📝 <b>Mevcut çekiliş metni:</b>\n\n"
        f"{current_text}\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Yeni çekiliş metnini şimdi tek mesaj olarak gönder.\n\n"
        "❌ Vazgeçmek için /iptal yazabilirsin.",
        parse_mode="HTML",
    )


# =========================================================
# ADMIN YENİ ÇEKİLİŞ METNİ
# =========================================================

async def save_new_giveaway_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    user = update.effective_user

    if not user or not message:
        return

    if not is_admin(user.id):
        return

    if message.chat.type != "private":
        return

    waiting = context.user_data.get(
        "waiting_for_giveaway_text",
        False,
    )

    if not waiting:
        return

    new_text = (message.text or "").strip()

    if not new_text:
        await message.reply_text(
            "❌ Metin boş olamaz."
        )
        return

    if len(new_text) > 3500:
        await message.reply_text(
            "❌ Çekiliş metni çok uzun.\n"
            "Lütfen 3500 karakterden kısa bir metin gönder."
        )
        return

    save_giveaway_text(
        escape(new_text)
    )

    context.user_data[
        "waiting_for_giveaway_text"
    ] = False

    await message.reply_text(
        "✅ <b>Çekiliş metni güncellendi.</b>\n\n"
        f"{escape(new_text)}\n\n"
        "Bu metin bundan sonraki /cekilis X "
        "komutlarında otomatik kullanılacak.",
        parse_mode="HTML",
    )

    logger.info(
        "Çekiliş metni admin tarafından güncellendi."
    )


# =========================================================
# /İPTAL
# =========================================================

async def cancel_text_edit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    user = update.effective_user

    if not user or not message:
        return

    if not is_admin(user.id):
        return

    if message.chat.type != "private":
        return

    context.user_data[
        "waiting_for_giveaway_text"
    ] = False

    await message.reply_text(
        "❌ Çekiliş metni değiştirme işlemi iptal edildi."
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
            f"❌ Bu bot yalnızca "
            f"{allowed_chat_text()} sohbetlerinde çalışır."
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
            "❌ Kullanım:\n"
            "/cekilis 3\n\n"
            "Buradaki sayı kazanan sayısını belirler."
        )
        return

    try:
        winner_count = int(context.args[0])
    except ValueError:
        await message.reply_text(
            "❌ Kazanan sayısı sayı olmalı.\n\n"
            "Örnek:\n"
            "/cekilis 3"
        )
        return

    if winner_count < 1:
        await message.reply_text(
            "❌ Kazanan sayısı en az 1 olmalı."
        )
        return

    custom_text = get_giveaway_text()

    initial_text = build_giveaway_text(
        custom_text,
        winner_count,
        0,
    )

    # =====================================================
    # ÇEKİLİŞ MESAJINI GÖNDER
    # =====================================================

    try:
        giveaway_message = await message.reply_text(
            initial_text,
            parse_mode="HTML",
            reply_markup=build_join_keyboard(0),
        )

    except Exception as error:
        logger.exception(
            "Çekiliş mesajı gönderilemedi: %s",
            error,
        )
        return

    # Mesaj gönderildikten sonra DB kaydı
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

    giveaway_id = cursor.lastrowid

    connection.commit()
    connection.close()

    # Gerçek giveaway ID'sini butona koy
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=chat.id,
            message_id=giveaway_message.message_id,
            reply_markup=build_join_keyboard(
                giveaway_id
            ),
        )
    except Exception as error:
        logger.warning(
            "KATIL butonu ID ile güncellenemedi: %s",
            error,
        )

    # =====================================================
    # ADMİNE BAŞLANGIÇ BİLDİRİMİ
    # =====================================================

    try:
        await context.bot.send_message(
            chat_id=ADMIN_RESULT_CHAT_ID,
            text=(
                "🎉 <b>Çekiliş başladı</b>\n\n"
                f"🏆 Kazanan sayısı: "
                f"<b>{winner_count}</b>\n"
                f"💬 Grup: "
                f"<b>{escape(chat.title or str(chat.id))}</b>\n"
                f"👥 Katılımcı: <b>0</b>\n\n"
                "🟢 Katılımlar alınmaya başladı."
            ),
            parse_mode="HTML",
        )

    except Exception as error:
        logger.warning(
            "Admin başlangıç bildirimi gönderilemedi: %s",
            error,
        )

    logger.info(
        "Çekiliş başlatıldı: giveaway_id=%s chat_id=%s winner_count=%s",
        giveaway_id,
        chat.id,
        winner_count,
    )


# =========================================================
# 🎟️ KATIL BUTONU
# =========================================================

async def join_giveaway_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    if not query:
        return

    user = query.from_user
    message = query.message

    if not user or not message:
        await query.answer()
        return

    # Butona basan kişinin chat'i
    chat = message.chat

    if chat.type not in ("group", "supergroup"):
        await query.answer(
            "❌ Bu buton yalnızca grupta kullanılabilir.",
            show_alert=True,
        )
        return

    if not chat.username:
        await query.answer(
            "❌ Bu grup desteklenmiyor.",
            show_alert=True,
        )
        return

    if normalize_username(chat.username) not in {
        normalize_username(name)
        for name in ALLOWED_CHAT_USERNAMES
    }:
        await query.answer(
            "❌ Bu çekiliş bu grupta kullanılamaz.",
            show_alert=True,
        )
        return

    # Callback'ten giveaway ID al
    data = query.data or ""

    if not data.startswith(JOIN_CALLBACK_PREFIX):
        await query.answer()
        return

    try:
        giveaway_id = int(
            data.replace(
                JOIN_CALLBACK_PREFIX,
                "",
                1,
            )
        )
    except ValueError:
        await query.answer(
            "❌ Geçersiz çekiliş.",
            show_alert=True,
        )
        return

    # Aktif çekiliş kontrolü
    connection = get_db()

    giveaway = connection.execute(
        """
        SELECT *
        FROM giveaways
        WHERE id = ?
          AND active = 1
        LIMIT 1
        """,
        (giveaway_id,),
    ).fetchone()

    if not giveaway:
        connection.close()

        await query.answer(
            "❌ Bu çekiliş artık aktif değil.",
            show_alert=True,
        )
        return

    if giveaway["chat_id"] != chat.id:
        connection.close()

        await query.answer(
            "❌ Bu çekiliş bu gruba ait değil.",
            show_alert=True,
        )
        return

    # =====================================================
    # AYNI TELEGRAM ID İKİNCİ KEZ KATILAMAZ
    # =====================================================

    existing = connection.execute(
        """
        SELECT id
        FROM participants
        WHERE giveaway_id = ?
          AND telegram_user_id = ?
        LIMIT 1
        """,
        (
            giveaway_id,
            user.id,
        ),
    ).fetchone()

    if existing:
        connection.close()

        await query.answer(
            "⚠️ Bu çekilişe zaten katıldın!",
            show_alert=True,
        )
        return

    telegram_username = (
        user.username
        if user.username
        else None
    )

    telegram_name = (
        user.full_name
        or "İsimsiz kullanıcı"
    )

    # Eski DB yapısındaki entered_username alanını
    # buton sistemiyle uyumlu tutuyoruz.
    entered_username = (
        telegram_username
        if telegram_username
        else telegram_name
    )

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
                giveaway_id,
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

        await query.answer(
            "⚠️ Bu çekilişe zaten katıldın!",
            show_alert=True,
        )
        return

    connection.close()

    # =====================================================
    # KATILIM SAYISINI GÜNCELLE
    # =====================================================

    participant_count = get_participant_count(
        giveaway_id
    )

    custom_text = get_giveaway_text()

    new_text = build_giveaway_text(
        custom_text,
        giveaway["winner_count"],
        participant_count,
    )

    try:
        await context.bot.edit_message_text(
            chat_id=chat.id,
            message_id=giveaway["message_id"],
            text=new_text,
            parse_mode="HTML",
            reply_markup=build_join_keyboard(
                giveaway_id
            ),
        )

    except Exception as error:
        logger.warning(
            "Katılım sonrası çekiliş mesajı güncellenemedi: %s",
            error,
        )

    await query.answer(
        "🎟️ Çekilişe başarıyla katıldın!",
        show_alert=False,
    )

    logger.info(
        "Yeni katılım: giveaway_id=%s user_id=%s username=%s",
        giveaway_id,
        user.id,
        user.username,
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
            f"❌ Bu bot yalnızca "
            f"{allowed_chat_text()} sohbetlerinde çalışır."
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

    # =====================================================
    # KATILIMCILARI AL
    # =====================================================

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

    # Önce çekilişi pasif yap
    connection.execute(
        """
        UPDATE giveaways
        SET active = 0,
            ended_at = ?
        WHERE id = ?
        """,
        (
            utc_now(),
            active["id"],
        ),
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
            "👥 Toplam katılımcı: <b>0</b>\n"
            f"🏆 Kazanan sayısı: "
            f"<b>{active['winner_count']}</b>\n\n"
            "❌ Bu çekilişte kazanan bulunamadı.\n\n"
            "🍀 Bir sonraki çekilişte bol şans!"
        )

        try:
            await context.bot.edit_message_text(
                chat_id=active["chat_id"],
                message_id=active["message_id"],
                text=no_winner_text,
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception as error:
            logger.warning(
                "Çekiliş bitiş mesajı güncellenemedi: %s",
                error,
            )

        # Admin DM
        try:
            await context.bot.send_message(
                chat_id=ADMIN_RESULT_CHAT_ID,
                text=(
                    "🏁 <b>Çekiliş sona erdi</b>\n\n"
                    "👥 Toplam katılımcı: <b>0</b>\n"
                    "❌ Kazanan bulunamadı."
                ),
                parse_mode="HTML",
            )
        except Exception as error:
            logger.warning(
                "Admin özel mesajı gönderilemedi: %s",
                error,
            )

        await message.reply_text(
            "🛑 <b>Çekiliş sonlandırıldı.</b>\n\n"
            "👥 Katılımcı: <b>0</b>\n"
            "❌ Kazanan yok.",
            parse_mode="HTML",
        )

        return

    # =====================================================
    # KAZANANLARI SEÇ
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

    for index, winner in enumerate(
        winners,
        start=1,
    ):
        telegram_username = (
            winner["telegram_username"]
        )

        if telegram_username:
            identity = f"@{telegram_username}"
        else:
            identity = winner["telegram_name"]

        identity_html = escape(identity)

        group_lines.append(
            f"{index}. {identity_html}"
        )

        admin_lines.append(
            f"{index}. <b>{identity_html}</b>\n"
            f"   🆔 Telegram ID: "
            f"<code>{winner['telegram_user_id']}</code>"
        )

    winners_text_group = "\n".join(
        group_lines
    )

    winners_text_admin = "\n\n".join(
        admin_lines
    )

    # =====================================================
    # GRUPTA ÇEKİLİŞ MESAJINI SONUCA DÖNÜŞTÜR
    # =====================================================

    custom_text = get_giveaway_text()

    finished_text = build_finished_text(
        custom_text,
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
            reply_markup=None,
        )

    except Exception as error:
        logger.warning(
            "Sonuç mesajı güncellenemedi: %s",
            error,
        )

    # =====================================================
    # ADMİNE ÖZEL SONUÇ
    # =====================================================

    admin_message = (
        "🏆 <b>Çekiliş sonuçları</b>\n\n"
        f"👥 Toplam katılımcı: "
        f"<b>{participant_count}</b>\n"
        f"🏆 Kazanan sayısı: "
        f"<b>{winner_count}</b>\n\n"
        "<b>🎉 KAZANANLAR</b>\n\n"
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
            "Admin sonuç mesajı gönderilemedi: %s",
            error,
        )

    # Stop komutuna ekstra kısa mesaj
    try:
        await message.reply_text(
            "🏁 <b>Çekiliş sonlandırıldı!</b>\n\n"
            f"👥 Toplam katılımcı: "
            f"<b>{participant_count}</b>\n"
            f"🏆 Kazanan: <b>{winner_count}</b>\n\n"
            "🎉 Kazananları tebrik ederiz!",
            parse_mode="HTML",
        )

    except Exception as error:
        logger.warning(
            "Grup sonuç özeti gönderilemedi: %s",
            error,
        )

    logger.info(
        "Çekiliş tamamlandı: giveaway_id=%s participants=%s winners=%s",
        active["id"],
        participant_count,
        winner_count,
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
            f"❌ Bu bot yalnızca "
            f"{allowed_chat_text()} sohbetlerinde çalışır."
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

    participant_count = get_participant_count(
        active["id"]
    )

    await message.reply_text(
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
            "Admin ID bulunamadı."
        )

    init_database()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # =====================================================
    # COMMAND HANDLERS
    # =====================================================

    application.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "myid",
            my_id,
        )
    )

    application.add_handler(
        CommandHandler(
            "cekilis",
            start_giveaway,
        )
    )

    application.add_handler(
        CommandHandler(
            "cekilismet",
            giveaway_text_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "iptal",
            cancel_text_edit,
        )
    )

    application.add_handler(
        CommandHandler(
            "stopcekilis",
            stop_giveaway,
        )
    )

    application.add_handler(
        CommandHandler(
            "cekilisdurum",
            giveaway_status,
        )
    )

    # =====================================================
    # 🎟️ KATIL CALLBACK
    # =====================================================

    application.add_handler(
        CallbackQueryHandler(
            join_giveaway_callback,
            pattern=r"^giveaway_join:\d+$",
        )
    )

    # =====================================================
    # ADMIN ÖZELDEN YENİ METİN ALMA
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.ChatType.PRIVATE,
            save_new_giveaway_text,
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "HEROPRIME Çekiliş Botu başlatılıyor..."
    )

    logger.info(
        "İzin verilen sohbetler: %s",
        ", ".join(
            f"@{name}"
            for name in sorted(
                ALLOWED_CHAT_USERNAMES
            )
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
