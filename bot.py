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
from telegram.error import Conflict
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

# Railway > Variables > BOT_TOKEN
#
# TOKEN KESİNLİKLE KODUN İÇİNE YAZILMAYACAK.
#
BOT_TOKEN = '8855111211:AAEmD37GcwYfgndcQTPGfnLpVoJ622Ot8ek'


# =========================================================
# ADMİNLER
# =========================================================

ADMIN_IDS_RAW = os.getenv(
    "ADMIN_IDS",
    "8845737995",
).strip()


ADMIN_RESULT_CHAT_ID_RAW = os.getenv(
    "ADMIN_RESULT_CHAT_ID",
    "8845737995",
).strip()


try:
    ADMIN_RESULT_CHAT_ID = int(
        ADMIN_RESULT_CHAT_ID_RAW
    )
except ValueError:
    ADMIN_RESULT_CHAT_ID = 0


ADMIN_RESULT_USERNAME = "@HeroPrimeMarketing"


# =========================================================
# İZİNLİ SOHBETLER
# =========================================================

ALLOWED_CHAT_USERNAMES = {
    "heroprimeduyuru",
    "heroprimesohbet",
}


MANAGEMENT_CHANNEL_USERNAME = (
    "heroprimeduyuru"
)


# =========================================================
# DATABASE
# =========================================================

DB_FILE = os.getenv(
    "DB_FILE",
    "giveaway.db",
).strip() or "giveaway.db"


# =========================================================
# ÇEKİLİŞ
# =========================================================

JOIN_CALLBACK_PREFIX = (
    "giveaway_join:"
)


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
    format=(
        "%(asctime)s - "
        "%(name)s - "
        "%(levelname)s - "
        "%(message)s"
    ),
    level=logging.INFO,
)


logger = logging.getLogger(
    "heroprime_bot"
)


# Gereksiz HTTP loglarını azalt
logging.getLogger(
    "httpx"
).setLevel(logging.WARNING)


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
            admin_ids.add(
                int(value)
            )

        except ValueError:

            logger.warning(
                "Geçersiz ADMIN_IDS değeri: %s",
                value,
            )

    return admin_ids


ADMIN_IDS = get_admin_ids()


def is_admin(
    user_id: int,
) -> bool:

    return user_id in ADMIN_IDS


# =========================================================
# GENEL YARDIMCI FONKSİYONLAR
# =========================================================

def normalize_username(
    username: str,
) -> str:

    return (
        (username or "")
        .strip()
        .lstrip("@")
        .lower()
    )


def get_chat_username(
    chat,
) -> str:

    if not chat:
        return ""

    return normalize_username(
        getattr(
            chat,
            "username",
            "",
        ) or ""
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


def is_allowed_chat(
    update: Update,
) -> bool:

    chat = update.effective_chat

    if not chat:
        return False

    if chat.type not in (
        "group",
        "supergroup",
        "channel",
    ):
        return False

    username = get_chat_username(
        chat
    )

    return username in {
        normalize_username(name)
        for name in ALLOWED_CHAT_USERNAMES
    }


def is_management_channel(
    update: Update,
) -> bool:

    chat = update.effective_chat

    if not chat:
        return False

    return (
        chat.type == "channel"
        and
        get_chat_username(chat)
        ==
        normalize_username(
            MANAGEMENT_CHANNEL_USERNAME
        )
    )


# =========================================================
# DATABASE BAĞLANTISI
# =========================================================

def get_db():

    connection = sqlite3.connect(
        DB_FILE,
        timeout=30,
    )

    connection.row_factory = sqlite3.Row

    return connection


# =========================================================
# DATABASE OLUŞTURMA
# =========================================================

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
# DATABASE - AKTİF ÇEKİLİŞ
# =========================================================

def get_active_giveaway():

    connection = get_db()

    try:

        row = connection.execute(
            """
            SELECT *
            FROM giveaways
            WHERE active = 1
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

        return row

    finally:

        connection.close()


# =========================================================
# DATABASE - KATILIMCI SAYISI
# =========================================================

def get_participant_count(
    giveaway_id: int,
) -> int:

    connection = get_db()

    try:

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

        return int(
            row["count"]
        )

    finally:

        connection.close()


# =========================================================
# DATABASE - ÇEKİLİŞ METNİ
# =========================================================

def get_giveaway_text() -> str:

    connection = get_db()

    try:

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

        if row and row["setting_value"]:
            return row["setting_value"]

        return DEFAULT_GIVEAWAY_TEXT

    finally:

        connection.close()


# =========================================================
# DATABASE - ÇEKİLİŞ METNİ KAYDET
# =========================================================

def save_giveaway_text(
    new_text: str,
):

    connection = get_db()

    try:

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

    finally:

        connection.close()


# =========================================================
# ÇEKİLİŞ MESAJI
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


# =========================================================
# ÇEKİLİŞ BİTİŞ MESAJI
# =========================================================

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


# =========================================================
# KATIL BUTONU
# =========================================================

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
# ADMİNE ÖZEL MESAJ
# =========================================================

async def send_admin_dm(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
):

    if ADMIN_RESULT_CHAT_ID == 0:

        logger.warning(
            "ADMIN_RESULT_CHAT_ID geçersiz."
        )

        return False

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
        and
        chat
        and
        chat.type in (
            "group",
            "supergroup",
        )
    ):

        try:

            member = (
                await context.bot.get_chat_member(
                    chat_id=chat.id,
                    user_id=user.id,
                )
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
# /START
# =========================================================
#
# ÖNEMLİ:
# Burada hiçbir kanal linki yok.
# Zorunlu kanal üyeliği yok.
# A-TOOLS yok.
# Reklam yok.
#
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.effective_message
    user = update.effective_user

    if not message or not user:
        return

    # -----------------------------------------------------
    # ADMIN
    # -----------------------------------------------------

    if (
        is_admin(user.id)
        and
        message.chat.type == "private"
    ):

        await message.reply_text(
            "🤖 <b>HEROPRIME Çekiliş Botu</b>\n\n"
            "✅ Bot aktif.\n\n"
            "👤 Admin erişimi doğrulandı.\n\n"
            "<b>Komutlar:</b>\n\n"
            "/myid\n"
            "/cekilismet\n"
            "/cekilis 3\n"
            "/cekilisdurum\n"
            "/stopcekilis\n"
            "/iptal",
            parse_mode="HTML",
        )

        return

    # -----------------------------------------------------
    # NORMAL KULLANICI
    # -----------------------------------------------------

    if message.chat.type == "private":

        await message.reply_text(
            "👋 <b>Hoş geldin!</b>\n\n"
            "🤖 HEROPRIME Çekiliş Botu aktif.\n\n"
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

    if not message or not user:
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

    if not message or not user:
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

    if not message or not user:
        return

    if (
        not is_admin(user.id)
        or
        message.chat.type != "private"
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
            "❌ Çekiliş metni çok uzun.\n\n"
            "Lütfen 3500 karakterden kısa "
            "bir metin gönder."
        )

        return

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

    if not message or not user:
        return

    if (
        not is_admin(user.id)
        or
        message.chat.type != "private"
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

    if not message or not chat:
        return

    # -----------------------------------------------------
    # SOHBET KONTROLÜ
    # -----------------------------------------------------

    if not is_allowed_chat(update):

        await message.reply_text(
            "❌ Bu bot yalnızca "
            f"{allowed_chat_text()} "
            "sohbetlerinde çalışır."
        )

        return

    # -----------------------------------------------------
    # YETKİ
    # -----------------------------------------------------

    if not await can_manage_giveaway(
        update,
        context,
    ):

        await message.reply_text(
            "❌ Bu komutu yalnızca "
            "çekiliş yöneticisi kullanabilir."
        )

        return

    # -----------------------------------------------------
    # ARGÜMAN
    # -----------------------------------------------------

    if len(context.args) != 1:

        await message.reply_text(
            "❌ Kullanım:\n\n"
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

    if winner_count > 100:

        await message.reply_text(
            "❌ Kazanan sayısı en fazla 100 olabilir."
        )

        return

    # -----------------------------------------------------
    # AKTİF ÇEKİLİŞ
    # -----------------------------------------------------

    active = get_active_giveaway()

    if active:

        await message.reply_text(
            "⚠️ Zaten aktif bir çekiliş var.\n\n"
            "Önce /stopcekilis ile mevcut "
            "çekilişi bitir."
        )

        return

    # -----------------------------------------------------
    # DB'YE ÖNCE KAYIT
    # -----------------------------------------------------

    started_by = (
        update.effective_user.id
        if update.effective_user
        else 0
    )

    connection = get_db()

    try:

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
                0,
                started_by,
                winner_count,
                utc_now(),
            ),
        )

        giveaway_id = cursor.lastrowid

        connection.commit()

    except Exception:

        connection.rollback()
        raise

    finally:

        connection.close()

    # -----------------------------------------------------
    # ÇEKİLİŞ MESAJI
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
                reply_markup=build_join_keyboard(
                    giveaway_id
                ),
            )
        )

    except Exception as error:

        logger.exception(
            "Çekiliş mesajı gönderilemedi: %s",
            error,
        )

        # Phantom kayıt bırakma
        connection = get_db()

        try:

            connection.execute(
                """
                DELETE FROM giveaways
                WHERE id = ?
                AND message_id = 0
                """,
                (
                    giveaway_id,
                ),
            )

            connection.commit()

        finally:

            connection.close()

        await message.reply_text(
            "❌ Çekiliş mesajı gönderilemedi.\n\n"
            "Botun bu sohbet içinde mesaj "
            "gönderme yetkisini kontrol et."
        )

        return

    # -----------------------------------------------------
    # GERÇEK MESSAGE ID
    # -----------------------------------------------------

    connection = get_db()

    try:

        connection.execute(
            """
            UPDATE giveaways
            SET message_id = ?
            WHERE id = ?
            """,
            (
                giveaway_message.message_id,
                giveaway_id,
            ),
        )

        connection.commit()

    finally:

        connection.close()

    # -----------------------------------------------------
    # ADMIN BİLDİRİMİ
    # -----------------------------------------------------

    chat_username = get_chat_username(
        chat
    )

    chat_title = (
        chat.title
        or
        chat_username
        or
        str(chat.id)
    )

    await send_admin_dm(
        context,
        "🚀 <b>ÇEKİLİŞ BAŞLADI</b>\n\n"
        f"💬 Sohbet: "
        f"<b>{escape(chat_title)}</b>\n"
        f"🏆 Kazanan sayısı: "
        f"<b>{winner_count}</b>\n"
        "👥 Katılımcı: <b>0</b>\n\n"
        "🟢 Katılımlar alınmaya başladı.",
    )

    logger.info(
        "Çekiliş başlatıldı: "
        "giveaway_id=%s "
        "chat_id=%s "
        "winner_count=%s",
        giveaway_id,
        chat.id,
        winner_count,
    )


# =========================================================
# 🎟️ KATIL
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

    try:

        # -------------------------------------------------
        # AKTİF ÇEKİLİŞ
        # -------------------------------------------------

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

            await query.answer(
                "❌ Bu çekiliş artık aktif değil.",
                show_alert=True,
            )

            return

        # -------------------------------------------------
        # SOHBET DOĞRULAMA
        # -------------------------------------------------

        giveaway_chat_id = giveaway[
            "chat_id"
        ]

        try:

            target_chat = (
                await context.bot.get_chat(
                    giveaway_chat_id
                )
            )

        except Exception as error:

            logger.warning(
                "Çekiliş sohbeti alınamadı: %s",
                error,
            )

            await query.answer(
                "❌ Çekiliş sohbeti doğrulanamadı.",
                show_alert=True,
            )

            return

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

            await query.answer(
                "❌ Geçersiz çekiliş sohbeti.",
                show_alert=True,
            )

            return

        if target_username not in {
            normalize_username(name)
            for name in ALLOWED_CHAT_USERNAMES
        }:

            await query.answer(
                "❌ Bu çekiliş bu sohbette "
                "kullanılamaz.",
                show_alert=True,
            )

            return

        # -------------------------------------------------
        # DAHA ÖNCE KATILDI MI?
        # -------------------------------------------------

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

            await query.answer(
                "⚠️ Bu çekilişe zaten katıldın!",
                show_alert=True,
            )

            return

        # -------------------------------------------------
        # KULLANICI
        # -------------------------------------------------

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
            or
            telegram_name
        )

        # -------------------------------------------------
        # KATILIM
        # -------------------------------------------------

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

            await query.answer(
                "⚠️ Bu çekilişe zaten katıldın!",
                show_alert=True,
            )

            return

    finally:

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
    # MESAJI GÜNCELLE
    # -----------------------------------------------------

    new_text = build_giveaway_text(
        get_giveaway_text(),
        giveaway["winner_count"],
        participant_count,
    )

    try:

        await context.bot.edit_message_text(
            chat_id=giveaway["chat_id"],
            message_id=giveaway["message_id"],
            text=new_text,
            parse_mode="HTML",
            reply_markup=build_join_keyboard(
                giveaway_id
            ),
        )

    except Exception as error:

        logger.warning(
            "Katılım sonrası mesaj güncellenemedi: %s",
            error,
        )

    # -----------------------------------------------------
    # SADECE BUTONA BASAN KİŞİYE POPUP
    # -----------------------------------------------------

    await query.answer(
        "🎟️ Çekilişe başarıyla katıldın!"
    )

    logger.info(
        "Yeni katılım: "
        "giveaway_id=%s "
        "user_id=%s "
        "username=%s",
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

    if not message or not chat:
        return

    # -----------------------------------------------------
    # SOHBET
    # -----------------------------------------------------

    if not is_allowed_chat(update):

        await message.reply_text(
            "❌ Bu bot yalnızca "
            f"{allowed_chat_text()} "
            "sohbetlerinde çalışır."
        )

        return

    # -----------------------------------------------------
    # YETKİ
    # -----------------------------------------------------

    if not await can_manage_giveaway(
        update,
        context,
    ):

        await message.reply_text(
            "❌ Bu komutu yalnızca "
            "çekiliş yöneticisi kullanabilir."
        )

        return

    # -----------------------------------------------------
    # AKTİF ÇEKİLİŞ
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # KATILIMCILAR
    # -----------------------------------------------------

    connection = get_db()

    try:

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

        participant_list = list(
            participants
        )

        participant_count = len(
            participant_list
        )

        # Önce pasifleştir
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

    finally:

        connection.close()

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

    winners = (
        secrets.SystemRandom().sample(
            participant_list,
            winner_count,
        )
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

    # Bu mesaj komutun kullanıldığı gruba gönderilir.
    await message.reply_text(
        "🏁 <b>Çekiliş sonlandırıldı!</b>\n\n"
        f"👥 Toplam katılımcı: "
        f"<b>{participant_count}</b>\n"
        f"🏆 Kazanan: "
        f"<b>{winner_count}</b>\n\n"
        "🎉 Kazananları tebrik ederiz!",
        parse_mode="HTML",
    )

    logger.info(
        "Çekiliş tamamlandı: "
        "giveaway_id=%s "
        "participants=%s "
        "winners=%s",
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

    if not message or not chat:
        return

    if not is_allowed_chat(update):

        await message.reply_text(
            "❌ Bu bot yalnızca "
            f"{allowed_chat_text()} "
            "sohbetlerinde çalışır."
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

    # -----------------------------------------------------
    # 409 CONFLICT
    # -----------------------------------------------------

    if isinstance(error, Conflict):

        logger.error(
            "================================================"
        )

        logger.error(
            "TELEGRAM 409 CONFLICT"
        )

        logger.error(
            "Bu bot tokenını kullanan başka bir "
            "getUpdates/polling bağlantısı var."
        )

        logger.error(
            "Railway'de tek instance çalıştığından ve "
            "aynı tokenın başka yerde kullanılmadığından "
            "emin ol."
        )

        logger.error(
            "================================================"
        )

        return

    # -----------------------------------------------------
    # DİĞER HATALAR
    # -----------------------------------------------------

    logger.error(
        "Telegram bot hatası: %s",
        error,
        exc_info=error,
    )


# =========================================================
# WEBHOOK TEMİZLEME
# =========================================================
#
# Polling'e başlamadan önce botun Telegram tarafında
# eski webhook'u varsa temizler.
#
# Bu, DOMAIN GEREKTİRMEZ.
#
# =========================================================

async def clear_old_webhook(
    application: Application,
):

    try:

        webhook_info = (
            await application.bot.get_webhook_info()
        )

        if webhook_info.url:

            logger.info(
                "Eski Telegram webhook'u bulundu. "
                "Temizleniyor..."
            )

            await application.bot.delete_webhook(
                drop_pending_updates=True
            )

            logger.info(
                "Eski webhook temizlendi."
            )

        else:

            logger.info(
                "Aktif Telegram webhook'u bulunamadı."
            )

    except Exception as error:

        logger.warning(
            "Eski webhook kontrolü/temizliği başarısız: %s",
            error,
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
            "Railway > Variables bölümüne:\n\n"
            "BOT_TOKEN=YENI_BOT_TOKEN\n\n"
            "ekle."
        )

    # -----------------------------------------------------
    # ADMIN
    # -----------------------------------------------------

    if not ADMIN_IDS:

        raise RuntimeError(
            "ADMIN_IDS bulunamadı."
        )

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
        .post_init(clear_old_webhook)
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
    # KATIL BUTONU
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
        "Mod: POLLING"
    )

    logger.info(
        "Webhook: KAPALI"
    )

    logger.info(
        "Domain: KULLANILMIYOR"
    )

    logger.info(
        "Kanal reklamı/zorunlu kanal: YOK"
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
        "=========================================="
    )

    # =====================================================
    # POLLING
    # =====================================================
    #
    # Telegram -> getUpdates -> Railway
    #
    # Domain gerekmez.
    #
    # =====================================================

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        bootstrap_retries=5,
    )


# =========================================================
# PROGRAM BAŞLANGICI
# =========================================================

if __name__ == "__main__":
    main()
