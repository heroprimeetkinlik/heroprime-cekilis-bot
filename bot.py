import os
import sqlite3
import secrets
import logging
from datetime import datetime, timezone
from html import escape
from urllib.parse import urlparse

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
BOT_TOKEN = '8855111211:AAEmD37GcwYfgndcQTPGfnLpVoJ622Ot8ek'

ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "8845737995").strip()
ADMIN_RESULT_CHAT_ID_RAW = os.getenv(
    "ADMIN_RESULT_CHAT_ID",
    "8845737995",
).strip()

try:
    ADMIN_RESULT_CHAT_ID = int(ADMIN_RESULT_CHAT_ID_RAW)
except ValueError:
    ADMIN_RESULT_CHAT_ID = 0

# @HeroPrimeMarketing korunuyor.
ADMIN_RESULT_USERNAME = "@HeroPrimeMarketing"

ALLOWED_CHAT_USERNAMES = {
    "heroprimeduyuru",
    "heroprimesohbet",
}
MANAGEMENT_CHANNEL_USERNAME = "heroprimeduyuru"

DB_FILE = os.getenv("DB_FILE", "giveaway.db").strip() or "giveaway.db"

JOIN_CALLBACK_PREFIX = "giveaway_join:"
EVENT_CALLBACK_PREFIX = "event:"

DEFAULT_GIVEAWAY_TEXT = (
    "🎉 <b>HEROPRIME ÇEKİLİŞ BAŞLADI!</b>\n\n"
    "🎟️ Çekilişe katılmak için aşağıdaki <b>KATIL</b> "
    "butonuna bas.\n\n"
    "🍀 <b>Herkese bol şans!</b>"
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("heroprime_bot")
logging.getLogger("httpx").setLevel(logging.WARNING)


# =========================================================
# ADMİN
# =========================================================

def get_admin_ids():
    result = set()
    for value in ADMIN_IDS_RAW.split(","):
        value = value.strip()
        if value.isdigit():
            result.add(int(value))
    return result

ADMIN_IDS = get_admin_ids()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# =========================================================
# GENEL
# =========================================================

def normalize_username(value: str) -> str:
    return (value or "").strip().lstrip("@").lower()


def get_chat_username(chat) -> str:
    if not chat:
        return ""
    return normalize_username(getattr(chat, "username", "") or "")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def allowed_chat_text() -> str:
    return "@heroprimeduyuru veya @heroprimesohbet"


def is_allowed_chat(update: Update) -> bool:
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup", "channel"):
        return False
    return get_chat_username(chat) in {
        normalize_username(x) for x in ALLOWED_CHAT_USERNAMES
    }


def is_management_channel(update: Update) -> bool:
    chat = update.effective_chat
    return bool(
        chat
        and chat.type == "channel"
        and get_chat_username(chat)
        == normalize_username(MANAGEMENT_CHANNEL_USERNAME)
    )


def get_db():
    connection = sqlite3.connect(DB_FILE, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


# =========================================================
# DATABASE
# =========================================================

def init_database():
    connection = get_db()
    cursor = connection.cursor()

    cursor.execute("""
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
    """)

    cursor.execute("""
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
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_chat_id INTEGER NOT NULL,
            post_message_id INTEGER NOT NULL,
            post_link TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS event_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            telegram_user_id INTEGER,
            telegram_username TEXT,
            entered_text TEXT NOT NULL,
            reply_message_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(event_id, reply_message_id),
            FOREIGN KEY(event_id) REFERENCES events(id)
        )
    """)

    row = cursor.execute(
        "SELECT setting_value FROM bot_settings WHERE setting_key = ?",
        ("giveaway_text",),
    ).fetchone()

    if row is None:
        cursor.execute(
            """
            INSERT INTO bot_settings(setting_key, setting_value, updated_at)
            VALUES (?, ?, ?)
            """,
            ("giveaway_text", DEFAULT_GIVEAWAY_TEXT, utc_now()),
        )

    connection.commit()
    connection.close()
    logger.info("Database hazır.")


def get_active_giveaway():
    connection = get_db()
    try:
        return connection.execute(
            """
            SELECT * FROM giveaways
            WHERE active = 1
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
    finally:
        connection.close()


def get_participant_count(giveaway_id: int) -> int:
    connection = get_db()
    try:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM participants WHERE giveaway_id = ?",
            (giveaway_id,),
        ).fetchone()
        return int(row["count"])
    finally:
        connection.close()


def get_giveaway_text() -> str:
    connection = get_db()
    try:
        row = connection.execute(
            "SELECT setting_value FROM bot_settings WHERE setting_key = ?",
            ("giveaway_text",),
        ).fetchone()
        return row["setting_value"] if row else DEFAULT_GIVEAWAY_TEXT
    finally:
        connection.close()


def save_giveaway_text(new_text: str):
    connection = get_db()
    try:
        connection.execute(
            """
            INSERT INTO bot_settings(setting_key, setting_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET
                setting_value=excluded.setting_value,
                updated_at=excluded.updated_at
            """,
            ("giveaway_text", new_text, utc_now()),
        )
        connection.commit()
    finally:
        connection.close()


# =========================================================
# ÇEKİLİŞ
# =========================================================

def build_giveaway_text(custom_text, winner_count, participant_count):
    return (
        f"{custom_text}\n\n"
        f"🏆 Kazanan sayısı: <b>{winner_count}</b>\n"
        f"👥 Katılımcı: <b>{participant_count}</b>"
    )


def build_finished_text(custom_text, participant_count, winner_count, winners_text):
    return (
        "🏁 <b>HEROPRIME ÇEKİLİŞ SONA ERDİ!</b>\n\n"
        f"{custom_text}\n\n"
        f"👥 Toplam katılımcı: <b>{participant_count}</b>\n"
        f"🏆 Kazanan sayısı: <b>{winner_count}</b>\n\n"
        "<b>🎉 KAZANANLAR</b>\n\n"
        f"{winners_text}\n\n"
        "🍀 <b>Tüm katılımcılara teşekkürler!</b>"
    )


def build_join_keyboard(giveaway_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🎟️ KATIL",
            callback_data=f"{JOIN_CALLBACK_PREFIX}{giveaway_id}",
        )
    ]])


async def send_admin_dm(context, text):
    if not ADMIN_RESULT_CHAT_ID:
        return False
    try:
        await context.bot.send_message(
            chat_id=ADMIN_RESULT_CHAT_ID,
            text=text,
            parse_mode="HTML",
        )
        return True
    except Exception as error:
        logger.warning("Admin özel mesajı gönderilemedi: %s", error)
        return False


async def can_manage_giveaway(update, context):
    user = update.effective_user
    chat = update.effective_chat

    if user and is_admin(user.id):
        return True

    if is_management_channel(update):
        return True

    if user and chat and chat.type in ("group", "supergroup"):
        try:
            member = await context.bot.get_chat_member(chat.id, user.id)
            return member.status in ("administrator", "creator")
        except Exception:
            return False

    return False


async def start_giveaway(update, context):
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    if not is_allowed_chat(update):
        await message.reply_text(
            f"❌ Bu bot yalnızca {allowed_chat_text()} sohbetlerinde çalışır."
        )
        return

    if not await can_manage_giveaway(update, context):
        await message.reply_text("❌ Bu komutu yalnızca çekiliş yöneticisi kullanabilir.")
        return

    if len(context.args) != 1:
        await message.reply_text("❌ Kullanım:\n/cekilis 3")
        return

    try:
        winner_count = int(context.args[0])
    except ValueError:
        await message.reply_text("❌ Kazanan sayısı sayı olmalı.\nÖrnek: /cekilis 3")
        return

    if winner_count < 1 or winner_count > 100:
        await message.reply_text("❌ Kazanan sayısı 1 ile 100 arasında olmalı.")
        return

    active = get_active_giveaway()
    if active:
        await message.reply_text(
            "⚠️ Zaten aktif bir çekiliş var.\nÖnce /stopcekilis ile bitir."
        )
        return

    started_by = update.effective_user.id if update.effective_user else 0

    connection = get_db()
    try:
        cursor = connection.execute(
            """
            INSERT INTO giveaways(
                chat_id, message_id, started_by, winner_count, active, created_at
            )
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (chat.id, 0, started_by, winner_count, utc_now()),
        )
        giveaway_id = cursor.lastrowid
        connection.commit()
    finally:
        connection.close()

    try:
        giveaway_message = await context.bot.send_message(
            chat_id=chat.id,
            text=build_giveaway_text(get_giveaway_text(), winner_count, 0),
            parse_mode="HTML",
            reply_markup=build_join_keyboard(giveaway_id),
        )
    except Exception:
        connection = get_db()
        try:
            connection.execute(
                "DELETE FROM giveaways WHERE id = ? AND message_id = 0",
                (giveaway_id,),
            )
            connection.commit()
        finally:
            connection.close()
        await message.reply_text("❌ Çekiliş mesajı gönderilemedi.")
        return

    connection = get_db()
    try:
        connection.execute(
            "UPDATE giveaways SET message_id = ? WHERE id = ?",
            (giveaway_message.message_id, giveaway_id),
        )
        connection.commit()
    finally:
        connection.close()

    title = chat.title or get_chat_username(chat) or str(chat.id)
    await send_admin_dm(
        context,
        "🚀 <b>ÇEKİLİŞ BAŞLADI</b>\n\n"
        f"💬 Sohbet: <b>{escape(title)}</b>\n"
        f"🏆 Kazanan sayısı: <b>{winner_count}</b>\n"
        "👥 Katılımcı: <b>0</b>\n\n"
        "🟢 Katılımlar alınmaya başladı.",
    )


async def join_giveaway_callback(update, context):
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    if not data.startswith(JOIN_CALLBACK_PREFIX):
        return

    user = query.from_user
    try:
        giveaway_id = int(data.replace(JOIN_CALLBACK_PREFIX, "", 1))
    except ValueError:
        await query.answer("❌ Geçersiz çekiliş.", show_alert=True)
        return

    connection = get_db()
    try:
        giveaway = connection.execute(
            """
            SELECT * FROM giveaways
            WHERE id = ? AND active = 1 LIMIT 1
            """,
            (giveaway_id,),
        ).fetchone()

        if not giveaway:
            await query.answer("❌ Bu çekiliş artık aktif değil.", show_alert=True)
            return

        existing = connection.execute(
            """
            SELECT id FROM participants
            WHERE giveaway_id = ? AND telegram_user_id = ? LIMIT 1
            """,
            (giveaway_id, user.id),
        ).fetchone()

        if existing:
            await query.answer("⚠️ Bu çekilişe zaten katıldın!", show_alert=True)
            return

        username = user.username
        name = user.full_name or "İsimsiz kullanıcı"
        entered = username or name

        connection.execute(
            """
            INSERT INTO participants(
                giveaway_id, telegram_user_id, telegram_username,
                telegram_name, entered_username, joined_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (giveaway_id, user.id, username, name, entered, utc_now()),
        )
        connection.commit()
    except sqlite3.IntegrityError:
        await query.answer("⚠️ Bu çekilişe zaten katıldın!", show_alert=True)
        return
    finally:
        connection.close()

    count = get_participant_count(giveaway_id)

    try:
        await context.bot.edit_message_text(
            chat_id=giveaway["chat_id"],
            message_id=giveaway["message_id"],
            text=build_giveaway_text(
                get_giveaway_text(),
                giveaway["winner_count"],
                count,
            ),
            parse_mode="HTML",
            reply_markup=build_join_keyboard(giveaway_id),
        )
    except Exception:
        pass

    await query.answer("🎟️ Çekilişe başarıyla katıldın!")


async def stop_giveaway(update, context):
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    if not is_allowed_chat(update):
        await message.reply_text(
            f"❌ Bu bot yalnızca {allowed_chat_text()} sohbetlerinde çalışır."
        )
        return

    if not await can_manage_giveaway(update, context):
        await message.reply_text("❌ Bu komutu yalnızca çekiliş yöneticisi kullanabilir.")
        return

    active = get_active_giveaway()
    if not active or active["chat_id"] != chat.id:
        await message.reply_text("❌ Bu sohbette aktif çekiliş yok.")
        return

    connection = get_db()
    try:
        participants = connection.execute(
            "SELECT * FROM participants WHERE giveaway_id = ? ORDER BY id ASC",
            (active["id"],),
        ).fetchall()
        connection.execute(
            """
            UPDATE giveaways
            SET active = 0, ended_at = ?
            WHERE id = ?
            """,
            (utc_now(), active["id"]),
        )
        connection.commit()
    finally:
        connection.close()

    if not participants:
        text = (
            "🏁 <b>HEROPRIME ÇEKİLİŞ SONA ERDİ!</b>\n\n"
            "👥 Toplam katılımcı: <b>0</b>\n"
            f"🏆 Kazanan sayısı: <b>{active['winner_count']}</b>\n\n"
            "❌ Bu çekilişte kazanan bulunamadı."
        )
        try:
            await context.bot.edit_message_text(
                chat_id=active["chat_id"],
                message_id=active["message_id"],
                text=text,
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            pass
        await send_admin_dm(
            context,
            "🏁 <b>ÇEKİLİŞ BİTTİ</b>\n\n"
            f"💬 Sohbet: <b>{escape(chat.title or str(chat.id))}</b>\n"
            "👥 Toplam katılımcı: <b>0</b>\n"
            "❌ Kazanan bulunamadı.",
        )
        return

    winner_count = min(active["winner_count"], len(participants))
    winners = secrets.SystemRandom().sample(list(participants), winner_count)

    group_lines = []
    admin_lines = []

    for i, winner in enumerate(winners, 1):
        identity = (
            f"@{winner['telegram_username']}"
            if winner["telegram_username"]
            else winner["telegram_name"]
        )
        safe = escape(identity)
        group_lines.append(f"{i}. {safe}")
        admin_lines.append(
            f"{i}. <b>{safe}</b>\n"
            f"   🆔 Telegram ID: <code>{winner['telegram_user_id']}</code>"
        )

    finished = build_finished_text(
        get_giveaway_text(),
        len(participants),
        winner_count,
        "\n".join(group_lines),
    )

    try:
        await context.bot.edit_message_text(
            chat_id=active["chat_id"],
            message_id=active["message_id"],
            text=finished,
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        pass

    await send_admin_dm(
        context,
        "🏁 <b>ÇEKİLİŞ BİTTİ</b>\n\n"
        f"💬 Sohbet: <b>{escape(chat.title or str(chat.id))}</b>\n"
        f"👥 Toplam katılımcı: <b>{len(participants)}</b>\n"
        f"🏆 Kazanan sayısı: <b>{winner_count}</b>\n\n"
        "<b>🎉 KAZANANLAR</b>\n\n"
        + "\n\n".join(admin_lines),
    )

    await message.reply_text(
        "🏁 <b>Çekiliş sonlandırıldı!</b>\n\n"
        f"👥 Toplam katılımcı: <b>{len(participants)}</b>\n"
        f"🏆 Kazanan: <b>{winner_count}</b>",
        parse_mode="HTML",
    )


async def giveaway_status(update, context):
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    if not is_allowed_chat(update):
        await message.reply_text(
            f"❌ Bu bot yalnızca {allowed_chat_text()} sohbetlerinde çalışır."
        )
        return

    active = get_active_giveaway()
    if not active or active["chat_id"] != chat.id:
        await message.reply_text("ℹ️ Bu sohbette aktif çekiliş yok.")
        return

    count = get_participant_count(active["id"])
    await message.reply_text(
        "📊 <b>ÇEKİLİŞ DURUMU</b>\n\n"
        f"🏆 Kazanan sayısı: <b>{active['winner_count']}</b>\n"
        f"👥 Katılımcı: <b>{count}</b>\n\n"
        "🟢 Çekiliş aktif.",
        parse_mode="HTML",
    )


# =========================================================
# ÇEKİLİŞ METNİ
# =========================================================

async def giveaway_text_command(update, context):
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return
    if message.chat.type != "private":
        await message.reply_text("🔒 Bu komut yalnızca özelden kullanılabilir.")
        return

    context.user_data["waiting_for_giveaway_text"] = True
    await message.reply_text(
        "📝 <b>Yeni çekiliş metnini gönder.</b>\n\n"
        "❌ Vazgeçmek için /iptal",
        parse_mode="HTML",
    )


async def save_new_giveaway_text(update, context):
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return
    if message.chat.type != "private":
        return
    if not context.user_data.get("waiting_for_giveaway_text"):
        return

    text = (message.text or "").strip()
    if not text:
        await message.reply_text("❌ Metin boş olamaz.")
        return
    if len(text) > 3500:
        await message.reply_text("❌ Metin 3500 karakterden kısa olmalı.")
        return

    safe = escape(text)
    save_giveaway_text(safe)
    context.user_data["waiting_for_giveaway_text"] = False

    await message.reply_text(
        "✅ <b>Çekiliş metni güncellendi.</b>\n\n"
        f"{safe}",
        parse_mode="HTML",
    )


async def cancel_text_edit(update, context):
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return
    if message.chat.type != "private":
        return

    context.user_data.clear()
    await message.reply_text("❌ İşlem iptal edildi.")


# =========================================================
# ETKİNLİK - POST YANITLARINI TOPLAMA
# =========================================================

def parse_public_post_link(link: str):
    link = (link or "").strip()

    if not link.startswith(("https://t.me/", "http://t.me/")):
        return None

    parsed = urlparse(link)
    parts = [x for x in parsed.path.split("/") if x]

    # Public: https://t.me/heroprimesohbet/1234
    if len(parts) >= 2 and parts[0] != "c":
        try:
            message_id = int(parts[1])
        except ValueError:
            return None

        return {
            "username": normalize_username(parts[0]),
            "message_id": message_id,
        }

    return None


def get_active_event():
    connection = get_db()
    try:
        return connection.execute(
            """
            SELECT * FROM events
            WHERE active = 1
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
    finally:
        connection.close()


def create_event(post_chat_id, post_message_id, post_link, created_by):
    connection = get_db()
    try:
        cursor = connection.execute(
            """
            INSERT INTO events(
                post_chat_id, post_message_id, post_link,
                created_by, created_at, active
            )
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (
                post_chat_id,
                post_message_id,
                post_link,
                created_by,
                utc_now(),
            ),
        )
        connection.commit()
        return cursor.lastrowid
    finally:
        connection.close()


def get_event_entries(event_id):
    connection = get_db()
    try:
        return connection.execute(
            """
            SELECT entered_text
            FROM event_entries
            WHERE event_id = ?
            ORDER BY id ASC
            """,
            (event_id,),
        ).fetchall()
    finally:
        connection.close()


def add_event_entry(event_id, message):
    text = (message.text or "").strip()
    if not text:
        return False

    user = message.from_user
    user_id = user.id if user else None
    username = user.username if user else None

    connection = get_db()
    try:
        try:
            connection.execute(
                """
                INSERT INTO event_entries(
                    event_id, telegram_user_id, telegram_username,
                    entered_text, reply_message_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    user_id,
                    username,
                    text,
                    message.message_id,
                    utc_now(),
                ),
            )
            connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    finally:
        connection.close()


def find_event_for_reply(chat_id, reply_message_id):
    connection = get_db()
    try:
        return connection.execute(
            """
            SELECT * FROM events
            WHERE active = 1
              AND post_chat_id = ?
              AND post_message_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (chat_id, reply_message_id),
        ).fetchone()
    finally:
        connection.close()


def event_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Post Linki İlet", callback_data="event:link")],
        [InlineKeyboardButton("📋 Liste", callback_data="event:list")],
        [InlineKeyboardButton("🛑 Etkinliği Kapat", callback_data="event:close")],
    ])


async def event_panel(update, context):
    message = update.effective_message
    user = update.effective_user

    if not message or not user or not is_admin(user.id):
        return

    if message.chat.type != "private":
        return

    active = get_active_event()

    if active:
        entries = get_event_entries(active["id"])
        status = (
            "🟢 <b>Aktif etkinlik</b>\n"
            f"👥 Toplanan yanıt: <b>{len(entries)}</b>\n"
            f"🔗 {escape(active['post_link'])}\n\n"
        )
    else:
        status = "⚪ Aktif etkinlik yok.\n\n"

    await message.reply_text(
        "🎯 <b>ETKİNLİK PANELİ</b>\n\n"
        f"{status}"
        "Post linkini gönderdiğinde bu postun bundan sonra "
        "gelen doğrudan yanıtlarının yazılarını kaydeder.\n\n"
        "⚠️ Telegram Bot API geçmişteki yanıtları linkten "
        "geriye dönük çekemez.",
        parse_mode="HTML",
        reply_markup=event_keyboard(),
    )


async def event_command(update, context):
    await event_panel(update, context)


async def event_callback(update, context):
    query = update.callback_query
    user = query.from_user if query else None

    if not query or not user or not is_admin(user.id):
        if query:
            await query.answer("❌ Yetkin yok.", show_alert=True)
        return

    data = query.data or ""

    if data == "event:panel":
        await query.answer()
        await event_panel(update, context)
        return

    if data == "event:link":
        context.user_data["waiting_for_event_link"] = True
        await query.answer()
        await query.message.reply_text(
            "🔗 Etkinlik postunun linkini gönder.\n\n"
            "Örnek:\n"
            "https://t.me/heroprimesohbet/1234\n\n"
            "❌ İptal: /iptal"
        )
        return

    if data == "event:list":
        active = get_active_event()
        if not active:
            await query.answer("❌ Aktif etkinlik yok.", show_alert=True)
            return

        entries = get_event_entries(active["id"])
        if not entries:
            await query.answer("Henüz yanıt toplanmadı.", show_alert=True)
            return

        lines = [
            f"{i}. {escape(row['entered_text'])}"
            for i, row in enumerate(entries, 1)
        ]
        text = (
            "📋 <b>ETKİNLİK İSİM LİSTESİ</b>\n\n"
            f"👥 Toplam: <b>{len(entries)}</b>\n\n"
            + "\n".join(lines)
        )

        await query.answer()

        if len(text) <= 3900:
            await query.message.reply_text(text, parse_mode="HTML")
        else:
            from io import BytesIO
            raw = "\n".join(
                f"{i}. {row['entered_text']}"
                for i, row in enumerate(entries, 1)
            ).encode("utf-8")
            file_obj = BytesIO(raw)
            file_obj.name = "etkinlik_listesi.txt"
            await query.message.reply_document(
                document=file_obj,
                caption=f"📋 Etkinlik listesi — {len(entries)} kişi",
            )
        return

    if data == "event:close":
        active = get_active_event()
        if not active:
            await query.answer("❌ Aktif etkinlik yok.", show_alert=True)
            return

        connection = get_db()
        try:
            connection.execute(
                "UPDATE events SET active = 0 WHERE id = ?",
                (active["id"],),
            )
            connection.commit()
        finally:
            connection.close()

        context.user_data["waiting_for_event_link"] = False
        await query.answer("Etkinlik kapatıldı.")
        await query.message.reply_text(
            "🛑 <b>Etkinlik kapatıldı.</b>",
            parse_mode="HTML",
        )


async def save_event_link(update, context):
    message = update.effective_message
    user = update.effective_user

    if not message or not user or not is_admin(user.id):
        return

    if message.chat.type != "private":
        return

    if not context.user_data.get("waiting_for_event_link"):
        return

    link = (message.text or "").strip()

    if link == "/iptal":
        context.user_data["waiting_for_event_link"] = False
        await message.reply_text("❌ Etkinlik işlemi iptal edildi.")
        return

    parsed = parse_public_post_link(link)
    if not parsed:
        await message.reply_text(
            "❌ Public Telegram post linki gönder.\n\n"
            "Örnek:\nhttps://t.me/heroprimesohbet/1234"
        )
        return

    if get_active_event():
        await message.reply_text(
            "⚠️ Zaten aktif bir etkinlik var. "
            "Önce etkinliği kapat."
        )
        return

    try:
        target_chat = await context.bot.get_chat(
            f"@{parsed['username']}"
        )
    except Exception as error:
        logger.warning("Etkinlik sohbeti alınamadı: %s", error)
        await message.reply_text(
            "❌ Postun bulunduğu sohbeti bot göremiyor.\n\n"
            "Botu ilgili sohbet/grup ve gerekiyorsa yorum grubuna ekle."
        )
        return

    event_id = create_event(
        target_chat.id,
        parsed["message_id"],
        link,
        user.id,
    )

    context.user_data["waiting_for_event_link"] = False

    await message.reply_text(
        "✅ <b>Etkinlik kaydedildi.</b>\n\n"
        f"🔗 {escape(link)}\n"
        f"🆔 Etkinlik: <code>{event_id}</code>\n\n"
        "📥 Bundan sonra bu posta doğrudan yanıt olarak "
        "yazılan metinleri otomatik topluyorum.\n\n"
        "📋 Liste butonundan isimleri alabilirsin.",
        parse_mode="HTML",
        reply_markup=event_keyboard(),
    )


async def collect_event_reply(update, context):
    message = update.effective_message

    if not message or not message.reply_to_message:
        return

    if not message.text or not message.text.strip():
        return

    event = find_event_for_reply(
        message.chat.id,
        message.reply_to_message.message_id,
    )

    if not event:
        return

    if add_event_entry(event["id"], message):
        logger.info(
            "Etkinlik yanıtı kaydedildi: event=%s message=%s",
            event["id"],
            message.message_id,
        )


# =========================================================
# /START
# =========================================================

async def start_command(update, context):
    message = update.effective_message
    user = update.effective_user

    if not message or not user or message.chat.type != "private":
        return

    if not is_admin(user.id):
        await message.reply_text(
            "👋 <b>Hoş geldin!</b>\n\n"
            "🤖 HEROPRIME bot aktif.\n"
            "🆔 /myid",
            parse_mode="HTML",
        )
        return

    await message.reply_text(
        "🤖 <b>HEROPRIME Çekiliş Botu</b>\n\n"
        "✅ Bot aktif.\n\n"
        "<b>Çekiliş:</b>\n"
        "/cekilismet\n"
        "/cekilis 3\n"
        "/cekilisdurum\n"
        "/stopcekilis\n\n"
        "<b>Etkinlik:</b>\n"
        "/etkinlik",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎯 Etkinlik", callback_data="event:panel")
        ]]),
    )


async def my_id(update, context):
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
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
# HATA / WEBHOOK
# =========================================================

async def error_handler(update, context):
    if isinstance(context.error, Conflict):
        logger.error(
            "409 Conflict: aynı BOT_TOKEN ile başka bir polling instance çalışıyor."
        )
        return
    logger.error("Telegram bot hatası: %s", context.error, exc_info=context.error)


async def clear_old_webhook(application):
    try:
        info = await application.bot.get_webhook_info()
        if info.url:
            await application.bot.delete_webhook(drop_pending_updates=True)
            logger.info("Eski webhook temizlendi.")
    except Exception as error:
        logger.warning("Webhook temizlenemedi: %s", error)


# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN bulunamadı. Railway Variables içine BOT_TOKEN ekle."
        )

    if not ADMIN_IDS:
        raise RuntimeError(
            "ADMIN_IDS bulunamadı. Railway Variables içine ADMIN_IDS ekle."
        )

    init_database()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(clear_old_webhook)
        .build()
    )

    # Çekiliş
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("myid", my_id))
    application.add_handler(CommandHandler("cekilis", start_giveaway))
    application.add_handler(CommandHandler("cekilismet", giveaway_text_command))
    application.add_handler(CommandHandler("stopcekilis", stop_giveaway))
    application.add_handler(CommandHandler("cekilisdurum", giveaway_status))
    application.add_handler(CommandHandler("iptal", cancel_text_edit))

    # Etkinlik
    application.add_handler(CommandHandler("etkinlik", event_command))
    application.add_handler(
        CallbackQueryHandler(
            event_callback,
            pattern=r"^event:(panel|link|list|close)$",
        )
    )

    # Çekiliş katıl
    application.add_handler(
        CallbackQueryHandler(
            join_giveaway_callback,
            pattern=r"^giveaway_join:\d+$",
        )
    )

    # Yeni etkinlik yanıtlarını yakala.
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            collect_event_reply,
        ),
        group=0,
    )

    # Özelden etkinlik linki.
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            save_event_link,
        ),
        group=0,
    )

    # Özelden çekiliş metni.
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            save_new_giveaway_text,
        ),
        group=1,
    )

    application.add_error_handler(error_handler)

    logger.info("HEROPRIME Çekiliş + Etkinlik Botu başlatılıyor...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        bootstrap_retries=5,
    )


if __name__ == "__main__":
    main()
