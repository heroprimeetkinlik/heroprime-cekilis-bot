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

# Railway > Variables
BOT_TOKEN = '8855111211:AAEP_Whgvs650b8Jy1jVmuk9J1uA-j6nbUI'

# Adminler
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "8845737995").strip()

ADMIN_RESULT_CHAT_ID = int(
    os.getenv("ADMIN_RESULT_CHAT_ID", "8845737995")
)

ADMIN_RESULT_USERNAME = "@HeroPrimeMarketing"

# =========================================================
# İZİNLİ SOHBETLER
# =========================================================

ALLOWED_CHAT_USERNAMES = {
    "heroprimeduyuru",
    "heroprimesohbet",
}

MANAGEMENT_CHANNEL_USERNAME = "heroprimeduyuru"

# Test kanalı
TEST_CHANNEL_USERNAME = "@testkanaliii00"

# =========================================================
# DATABASE
# =========================================================

DB_FILE = os.getenv(
    "DB_FILE",
    "giveaway.db",
)

# =========================================================
# WEBHOOK
# =========================================================

# Railway Variables içine:
#
# WEBHOOK_URL=https://senin-domainin.up.railway.app
#
# Eğer WEBHOOK_URL girilmezse Railway'in
# RAILWAY_PUBLIC_DOMAIN değişkeninden otomatik oluşturulur.

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()

if not WEBHOOK_URL:
    railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()

    if railway_domain:
        if railway_domain.startswith("http://"):
            WEBHOOK_URL = railway_domain.replace(
                "http://",
                "https://",
                1,
            )
        elif railway_domain.startswith("https://"):
            WEBHOOK_URL = railway_domain
        else:
            WEBHOOK_URL = f"https://{railway_domain}"

# Webhook URL yolu
WEBHOOK_PATH = os.getenv(
    "WEBHOOK_PATH",
    "heroprime-telegram-webhook",
).strip().strip("/")

# Telegram webhook secret token
#
# Railway Variables içine WEBHOOK_SECRET_TOKEN koyarsan
# onu kullanır.
#
# Girilmezse uygulama her açılışta güvenli rastgele token üretir.
WEBHOOK_SECRET_TOKEN = os.getenv(
    "WEBHOOK_SECRET_TOKEN",
    "",
).strip()

if not WEBHOOK_SECRET_TOKEN:
    WEBHOOK_SECRET_TOKEN = secrets.token_urlsafe(32)

# Railway'in verdiği port
PORT = int(
    os.getenv(
        "PORT",
        "8080",
    )
)

# =========================================================
# ÇEKİLİŞ
# =========================================================

JOIN_CALLBACK_PREFIX = "giveaway_join:"

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

# httpx gereksiz request loglarını azalt
logging.getLogger("httpx").setLevel(logging.WARNING)


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
# GENEL YARDIMCI FONKSİYONLAR
# =========================================================

def normalize_username(username: str) -> str:
    return (
        (username or "")
        .strip()
        .lstrip("@")
        .lower()
    )


def get_chat_username(chat) -> str:
    return normalize_username(
        getattr(chat, "username", "") or ""
    )


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def allowed_chat_text() -> str:
    return (
        "@heroprimeduyuru veya "
        "@heroprimesohbet"
    )


def is_allowed_chat(update: Update) -> bool:
    chat = update.effective_chat

    if not chat:
        return False

    if chat.type not in (
        "group",
        "supergroup",
        "channel",
    ):
        return False

    return get_chat_username(chat) in {
        normalize_username(name)
        for name in ALLOWED_CHAT_USERNAMES
    }


def is_management_channel(update: Update) -> bool:
    chat = update.effective_chat

    return bool(
        chat
        and chat.type == "channel"
        and get_chat_username(chat)
        == normalize_username(
            MANAGEMENT_CHANNEL_USERNAME
        )
    )


# =========================================================
# DATABASE
# =========================================================

def get_db():
    connection = sqlite3.connect(
        DB_FILE,
        timeout=30,
    )

    connection.row_factory = sqlite3.Row

    return connection


def init_database():
    connection = get_db()
    cursor = connection.cursor()

    # -----------------------------------------------------
    # ÇEKİLİŞLER
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # KATILIMCILAR
    # -----------------------------------------------------

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

            UNIQUE(
                giveaway_id,
                telegram_user_id
            ),

            FOREIGN KEY(
                giveaway_id
            )
            REFERENCES giveaways(id)
        )
        """
    )

    # -----------------------------------------------------
    # BOT AYARLARI
    # -----------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    # -----------------------------------------------------
    # DEFAULT ÇEKİLİŞ METNİ
    # -----------------------------------------------------

    row = cursor.execute(
        """
        SELECT setting_value
        FROM bot_settings
        WHERE setting_key = ?
        """,
        (
            "giveaway_text",
        ),
    ).fetchone()

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

    logger.info(
        "Database hazır."
    )


# =========================================================
# DATABASE HELPERS
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


def get_participant_count(
    giveaway_id: int,
) -> int:

    connection = get_db()

    row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM participants
        WHERE giveaway_id = ?
        """,
        (
            giveaway_id,
        ),
    ).fetchone()

    connection.close()

    return int(
        row["count"]
    )


def get_giveaway_text() -> str:

    connection = get_db()

    row = connection.execute(
        """
        SELECT setting_value
        FROM bot_settings
        WHERE setting_key = ?
        """,
        (
            "giveaway_text",
        ),
    ).fetchone()

    connection.close()

    if row and row["setting_value"]:
        return row["setting_value"]

    return DEFAULT_GIVEAWAY_TEXT


def save_giveaway_text(
    new_text: str,
):
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
            setting_value =
                excluded.setting_value,
            updated_at =
                excluded.updated_at
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
        f"🏆 Kazanan sayısı: "
        f"<b>{winner_count}</b>\n"
        f"👥 Katılımcı: "
        f"<b>{participant_count}</b>"
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
        f"👥 Toplam katılımcı: "
        f"<b>{participant_count}</b>\n"
        f"🏆 Kazanan sayısı: "
        f"<b>{winner_count}</b>\n\n"
        "<b>🎉 KAZANANLAR</b>\n\n"
        f"{winners_text}\n\n"
        "🍀 <b>Tüm katılımcılara teşekkürler!</b>"
    )


def build_join_keyboard(
    giveaway_id: int,
):

    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(
                "🎟️ KATIL",
                callback_data=(
                    f"{JOIN_CALLBACK_PREFIX}"
                    f"{giveaway_id}"
                ),
            )
        ]]
    )


# =========================================================
# ADMIN DM
# =========================================================

async def send_admin_dm(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
):

    try:

        await context.bot.send_message(
            chat_id=ADMIN_RESULT_CHAT_ID,
            text=text,
            parse_mode="HTML",
        )

        return True

    except Exception as error:

        logger.warning(
            "Admin özel mesajı gönderilemedi: %s",
            error,
        )

        return False


# =========================================================
# ÇEKİLİŞ YÖNETİCİSİ KONTROLÜ
# =========================================================

async def can_manage_giveaway(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:

    user = update.effective_user
    chat = update.effective_chat

    # Ana admin
    if user and is_admin(user.id):
        return True

    # Yönetim kanalı
    if is_management_channel(update):
        return True

    # Grup yöneticisi
    if (
        user
        and chat
        and chat.type in (
            "group",
            "supergroup",
        )
    ):

        try:

            member = await context.bot.get_chat_member(
                chat_id=chat.id,
                user_id=user.id,
            )

            return member.status in (
                "administrator",
                "creator",
            )

        except Exception as error:

            logger.warning(
                "Grup admin kontrolü başarısız: %s",
                error,
            )

    return False


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

    # -----------------------------------------------------
    # ADMIN PRIVATE
    # -----------------------------------------------------

    if (
        is_admin(user.id)
        and message.chat.type == "private"
    ):

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

    # -----------------------------------------------------
    # NORMAL USER
    # -----------------------------------------------------

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
                "Kanala katıldıktan sonra "
                "tekrar /start gönder.",
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
        f"Kullanıcı adı: "
        f"{escape(username)}\n"
        f"Ad: "
        f"{escape(user.full_name)}",
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

    if not is_admin(user.id):

        await message.reply_text(
            "❌ Bu komutu yalnızca "
            "çekiliş yöneticisi kullanabilir."
        )

        return

    if message.chat.type != "private":

        await message.reply_text(
            "🔒 /cekilismet komutu yalnızca "
            "botla özel mesajda kullanılabilir."
        )

        return

    context.user_data[
        "waiting_for_giveaway_text"
    ] = True

    await message.reply_text(
        "📝 <b>Mevcut çekiliş metni:</b>\n\n"
        f"{get_giveaway_text()}\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Yeni çekiliş metnini şimdi "
        "tek mesaj olarak gönder.\n\n"
        "❌ Vazgeçmek için /iptal yazabilirsin.",
        parse_mode="HTML",
    )


# =========================================================
# ADMIN YENİ METİN
# =========================================================

async def save_new_giveaway_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.effective_message
    user = update.effective_user

    if not user or not message:
        return

    if (
        not is_admin(user.id)
        or message.chat.type != "private"
    ):
        return

    if not context.user_data.get(
        "waiting_for_giveaway_text",
        False,
    ):
        return

    new_text = (
        message.text or ""
    ).strip()

    if not new_text:

        await message.reply_text(
            "❌ Metin boş olamaz."
        )

        return

    if len(new_text) > 3500:

        await message.reply_text(
            "❌ Çekiliş metni çok uzun. "
            "Lütfen 3500 karakterden kısa "
            "bir metin gönder."
        )

        return

    # Güvenli HTML
    safe_text = escape(
        new_text
    )

    save_giveaway_text(
        safe_text
    )

    context.user_data[
        "waiting_for_giveaway_text"
    ] = False

    await message.reply_text(
        "✅ <b>Çekiliş metni güncellendi.</b>\n\n"
        f"{safe_text}\n\n"
        "Bu metin bundan sonraki "
        "/cekilis X komutlarında "
        "otomatik kullanılacak.",
        parse_mode="HTML",
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

    if (
        not is_admin(user.id)
        or message.chat.type != "private"
    ):
        return

    context.user_data[
        "waiting_for_giveaway_text"
    ] = False

    await message.reply_text(
        "❌ Çekiliş metni değiştirme "
        "işlemi iptal edildi."
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

    if not chat or not message:
        return

    # Sohbet kontrolü
    if not is_allowed_chat(update):

        await message.reply_text(
            f"❌ Bu bot yalnızca "
            f"{allowed_chat_text()} "
            f"sohbetlerinde çalışır."
        )

        return

    # Yetki kontrolü
    if not await can_manage_giveaway(
        update,
        context,
    ):

        await message.reply_text(
            "❌ Bu komutu yalnızca "
            "çekiliş yöneticisi kullanabilir."
        )

        return

    # Argüman kontrolü
    if len(context.args) != 1:

        await message.reply_text(
            "❌ Kullanım:\n"
            "/cekilis 3\n\n"
            "Buradaki sayı kazanan sayısını "
            "belirler."
        )

        return

    try:

        winner_count = int(
            context.args[0]
        )

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

    # Aktif çekiliş kontrolü
    active = get_active_giveaway()

    if active:

        await message.reply_text(
            "⚠️ Zaten aktif bir çekiliş var.\n\n"
            "Önce /stopcekilis ile mevcut "
            "çekilişi bitir."
        )

        return

    # -----------------------------------------------------
    # İLK MESAJ
    # -----------------------------------------------------

    initial_text = build_giveaway_text(
        get_giveaway_text(),
        winner_count,
        0,
    )

    try:

        giveaway_message = (
            await context.bot.send_message(
                chat_id=chat.id,
                text=initial_text,
                parse_mode="HTML",
                reply_markup=build_join_keyboard(0),
            )
        )

    except Exception as error:

        logger.exception(
            "Çekiliş mesajı gönderilemedi: %s",
            error,
        )

        try:

            await message.reply_text(
                "❌ Çekiliş mesajı gönderilemedi.\n\n"
                "Botun bu kanal/grupta mesaj "
                "gönderme yetkisini kontrol et."
            )

        except Exception:
            pass

        return

    started_by = (
        update.effective_user.id
        if update.effective_user
        else next(
            iter(ADMIN_IDS),
            ADMIN_RESULT_CHAT_ID,
        )
    )

    # -----------------------------------------------------
    # DATABASE KAYDI
    # -----------------------------------------------------

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
            started_by,
            winner_count,
            utc_now(),
        ),
    )

    giveaway_id = cursor.lastrowid

    connection.commit()
    connection.close()

    # -----------------------------------------------------
    # GERÇEK ÇEKİLİŞ ID'SİNİ BUTONA YAZ
    # -----------------------------------------------------

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
            "KATIL butonu güncellenemedi: %s",
            error,
        )

    # -----------------------------------------------------
    # ADMIN BİLDİRİMİ
    # -----------------------------------------------------

    chat_username = get_chat_username(
        chat
    )

    chat_link = (
        f"@{chat_username}"
        if chat_username
        else str(chat.id)
    )

    chat_title = (
        chat.title
        or chat_username
        or str(chat.id)
    )

    await send_admin_dm(
        context,
        "🚀 <b>ÇEKİLİŞ BAŞLADI</b>\n\n"
        f"💬 Sohbet: "
        f"<b>{escape(chat_title)}</b>\n"
        f"🔗 {escape(chat_link)}\n"
        f"🏆 Kazanan sayısı: "
        f"<b>{winner_count}</b>\n"
        "👥 Katılımcı: <b>0</b>\n\n"
        "🟢 Katılımlar alınmaya başladı.",
    )

    logger.info(
        "Çekiliş başlatıldı: "
        "giveaway_id=%s chat_id=%s winner_count=%s",
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
    data = query.data or ""

    if not user:

        await query.answer()
        return

    if not data.startswith(
        JOIN_CALLBACK_PREFIX
    ):

        await query.answer()
        return

    # -----------------------------------------------------
    # ID
    # -----------------------------------------------------

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

    connection = get_db()

    # -----------------------------------------------------
    # AKTİF ÇEKİLİŞ
    # -----------------------------------------------------

    giveaway = connection.execute(
        """
        SELECT *
        FROM giveaways
        WHERE id = ?
        AND active = 1
        LIMIT 1
        """,
        (
            giveaway_id,
        ),
    ).fetchone()

    if not giveaway:

        connection.close()

        await query.answer(
            "❌ Bu çekiliş artık aktif değil.",
            show_alert=True,
        )

        return

    giveaway_chat_id = giveaway[
        "chat_id"
    ]

    # -----------------------------------------------------
    # SOHBET DOĞRULAMA
    # -----------------------------------------------------

    try:

        target_chat = (
            await context.bot.get_chat(
                giveaway_chat_id
            )
        )

        target_username = (
            get_chat_username(
                target_chat
            )
        )

        if target_chat.type not in (
            "group",
            "supergroup",
            "channel",
        ):
            raise ValueError(
                "Desteklenmeyen sohbet türü"
            )

        if target_username not in {
            normalize_username(name)
            for name in ALLOWED_CHAT_USERNAMES
        }:

            connection.close()

            await query.answer(
                "❌ Bu çekiliş bu sohbette "
                "kullanılamaz.",
                show_alert=True,
            )

            return

    except Exception as error:

        connection.close()

        logger.warning(
            "Çekiliş sohbeti doğrulanamadı: %s",
            error,
        )

        await query.answer(
            "❌ Çekiliş sohbeti doğrulanamadı.",
            show_alert=True,
        )

        return

    # -----------------------------------------------------
    # DAHA ÖNCE KATILMIŞ MI?
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # KULLANICI BİLGİLERİ
    # -----------------------------------------------------

    telegram_username = (
        user.username
        if user.username
        else None
    )

    telegram_name = (
        user.full_name
        or "İsimsiz kullanıcı"
    )

    entered_username = (
        telegram_username
        or telegram_name
    )

    # -----------------------------------------------------
    # KATILIMI KAYDET
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # KATILIMCI SAYISI
    # -----------------------------------------------------

    participant_count = (
        get_participant_count(
            giveaway_id
        )
    )

    # -----------------------------------------------------
    # ÇEKİLİŞ MESAJINI GÜNCELLE
    # -----------------------------------------------------

    new_text = build_giveaway_text(
        get_giveaway_text(),
        giveaway["winner_count"],
        participant_count,
    )

    try:

        await context.bot.edit_message_text(
            chat_id=giveaway_chat_id,
            message_id=giveaway["message_id"],
            text=new_text,
            parse_mode="HTML",
            reply_markup=build_join_keyboard(
                giveaway_id
            ),
        )

    except Exception as error:

        logger.warning(
            "Katılım sonrası çekiliş mesajı "
            "güncellenemedi: %s",
            error,
        )

    # -----------------------------------------------------
    # ÖNEMLİ:
    # GRUBA MESAJ GÖNDERMEYİZ.
    #
    # Sadece butona basan kullanıcıya
    # Telegram callback bildirimi gösterilir.
    # -----------------------------------------------------

    await query.answer(
        "🎟️ Çekilişe başarıyla katıldın!"
    )

    logger.info(
        "Yeni katılım: giveaway_id=%s "
        "user_id=%s username=%s",
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

    if not chat or not message:
        return

    if not is_allowed_chat(update):

        await message.reply_text(
            f"❌ Bu bot yalnızca "
            f"{allowed_chat_text()} "
            f"sohbetlerinde çalışır."
        )

        return

    if not await can_manage_giveaway(
        update,
        context,
    ):

        await message.reply_text(
            "❌ Bu komutu yalnızca "
            "çekiliş yöneticisi kullanabilir."
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
        (
            active["id"],
        ),
    ).fetchall()

    # Çekilişi pasif yap
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

    participant_list = list(
        participants
    )

    participant_count = len(
        participant_list
    )

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

        await send_admin_dm(
            context,
            "🏁 <b>ÇEKİLİŞ BİTTİ</b>\n\n"
            f"💬 Sohbet: "
            f"<b>{escape(chat.title or str(chat.id))}</b>\n"
            "👥 Toplam katılımcı: <b>0</b>\n"
            "❌ Kazanan bulunamadı.",
        )

        try:

            await message.reply_text(
                "🛑 <b>Çekiliş sonlandırıldı.</b>\n\n"
                "👥 Katılımcı: <b>0</b>\n"
                "❌ Kazanan yok.",
                parse_mode="HTML",
            )

        except Exception:
            pass

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

        identity = (
            f"@{telegram_username}"
            if telegram_username
            else winner["telegram_name"]
        )

        identity_html = escape(
            identity
        )

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
    # SONUÇ MESAJI
    # =====================================================

    finished_text = build_finished_text(
        get_giveaway_text(),
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
    # ADMIN SONUÇ
    # =====================================================

    await send_admin_dm(
        context,
        "🏁 <b>ÇEKİLİŞ BİTTİ</b>\n\n"
        f"💬 Sohbet: "
        f"<b>{escape(chat.title or str(chat.id))}</b>\n"
        f"👥 Toplam katılımcı: "
        f"<b>{participant_count}</b>\n"
        f"🏆 Kazanan sayısı: "
        f"<b>{winner_count}</b>\n\n"
        "<b>🎉 KAZANANLAR</b>\n\n"
        f"{winners_text_admin}",
    )

    try:

        await message.reply_text(
            "🏁 <b>Çekiliş sonlandırıldı!</b>\n\n"
            f"👥 Toplam katılımcı: "
            f"<b>{participant_count}</b>\n"
            f"🏆 Kazanan: "
            f"<b>{winner_count}</b>\n\n"
            "🎉 Kazananları tebrik ederiz!",
            parse_mode="HTML",
        )

    except Exception as error:

        logger.warning(
            "Grup sonuç özeti gönderilemedi: %s",
            error,
        )

    logger.info(
        "Çekiliş tamamlandı: "
        "giveaway_id=%s participants=%s winners=%s",
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
            f"{allowed_chat_text()} "
            f"sohbetlerinde çalışır."
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

    participant_count = (
        get_participant_count(
            active["id"]
        )
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

    error = context.error

    logger.error(
        "Telegram bot hatası: %s",
        error,
        exc_info=error,
    )


# =========================================================
# WEBHOOK BİLGİLERİ
# =========================================================

def get_webhook_url() -> str:

    if not WEBHOOK_URL:
        raise RuntimeError(
            "WEBHOOK_URL bulunamadı.\n\n"
            "Railway Variables içine:\n"
            "WEBHOOK_URL=https://senin-railway-domainin\n"
            "ekle."
        )

    return (
        WEBHOOK_URL.rstrip("/")
        + "/"
        + WEBHOOK_PATH
    )


# =========================================================
# MAIN
# =========================================================

def main():

    # -----------------------------------------------------
    # TOKEN
    # -----------------------------------------------------

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN bulunamadı.\n\n"
            "Railway > Variables bölümüne "
            "BOT_TOKEN ekle."
        )

    # -----------------------------------------------------
    # ADMIN
    # -----------------------------------------------------

    if not ADMIN_IDS:

        raise RuntimeError(
            "ADMIN_IDS bulunamadı."
        )

    # -----------------------------------------------------
    # WEBHOOK URL
    # -----------------------------------------------------

    webhook_url = get_webhook_url()

    # -----------------------------------------------------
    # DATABASE
    # -----------------------------------------------------

    init_database()

    # -----------------------------------------------------
    # APPLICATION
    # -----------------------------------------------------

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # =====================================================
    # COMMANDS
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
    # KATIL CALLBACK
    # =====================================================

    application.add_handler(
        CallbackQueryHandler(
            join_giveaway_callback,
            pattern=r"^giveaway_join:\d+$",
        )
    )

    # =====================================================
    # ADMIN PRIVATE TEXT
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.ChatType.PRIVATE,
            save_new_giveaway_text,
        )
    )

    # =====================================================
    # ERROR HANDLER
    # =====================================================

    application.add_error_handler(
        error_handler
    )

    # =====================================================
    # LOG
    # =====================================================

    logger.info(
        "=========================================="
    )

    logger.info(
        "HEROPRIME Çekiliş Botu başlatılıyor..."
    )

    logger.info(
        "Telegram çalışma modu: WEBHOOK"
    )

    logger.info(
        "Webhook URL: %s",
        webhook_url,
    )

    logger.info(
        "Webhook portu: %s",
        PORT,
    )

    logger.info(
        "Polling KULLANILMIYOR."
    )

    logger.info(
        "getUpdates KULLANILMIYOR."
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

    logger.info(
        "=========================================="
    )

    # =====================================================
    # WEBHOOK
    # =====================================================
    #
    # BURADA run_polling YOK.
    #
    # getUpdates YOK.
    #
    # Telegram -> HTTPS Webhook -> Railway
    #
    # =====================================================

    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=webhook_url,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        secret_token=WEBHOOK_SECRET_TOKEN,
        max_connections=40,
    )


# =========================================================
# PROGRAM BAŞLANGICI
# =========================================================

if __name__ == "__main__":
    main()
