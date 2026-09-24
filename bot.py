import os
import sqlite3
import logging
import json
import re
from datetime import datetime, timezone
from html import escape
from urllib.parse import urlparse

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

BOT_TOKEN = '8862557397:AAFy7B3L7wfdvaPMGAYdDCAcA-FBmwQVh1s'

ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "8845737995").strip()

DB_FILE = os.getenv("DB_FILE", "sites.db").strip() or "sites.db"

ALLOWED_CHAT_USERNAMES = {
    "heroprimeduyuru",
    "heroprimesohbet",
}

SITE_ADMIN_PREFIX = "siteadmin:"

SITE_MAX_NAME = 80
SITE_MAX_URL = 1000
SITE_MAX_TEXT = 3500

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("heroprime_site_bot")

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

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_username(value: str) -> str:
    return (value or "").strip().lstrip("@").lower()


def get_chat_username(chat) -> str:
    if not chat:
        return ""

    return normalize_username(
        getattr(chat, "username", "") or ""
    )


def is_allowed_chat(update: Update) -> bool:
    chat = update.effective_chat

    if not chat:
        return False

    if chat.type not in ("group", "supergroup", "channel"):
        return False

    username = get_chat_username(chat)

    return username in {
        normalize_username(x)
        for x in ALLOWED_CHAT_USERNAMES
    }


def allowed_chat_text() -> str:
    return "@heroprimeduyuru veya @heroprimesohbet"


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
    # SİTELER
    # -----------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            visible INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )

    # -----------------------------------------------------
    # TANITIMLAR
    # -----------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS promotions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command TEXT NOT NULL UNIQUE,
            image_file_id TEXT,
            text TEXT NOT NULL,
            buttons_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    connection.commit()
    connection.close()

    logger.info("Site veritabanı hazır.")


# =========================================================
# SITE FONKSİYONLARI
# =========================================================

def normalize_site_command(value: str) -> str:
    value = (value or "").strip().lower()

    value = value.lstrip("!./")

    value = re.sub(
        r"[^a-z0-9_]+",
        "",
        value,
    )

    return value[:40]


def valid_http_url(value: str) -> bool:
    try:
        parsed = urlparse(
            (value or "").strip()
        )

        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.netloc)
        )

    except Exception:
        return False


def get_sites(visible_only=True):
    connection = get_db()

    try:
        sql = "SELECT * FROM sites"
        params = ()

        if visible_only:
            sql += " WHERE visible = 1"

        sql += " ORDER BY sort_order ASC, id ASC"

        return connection.execute(
            sql,
            params,
        ).fetchall()

    finally:
        connection.close()


def get_site(site_id):
    connection = get_db()

    try:
        return connection.execute(
            "SELECT * FROM sites WHERE id = ?",
            (site_id,),
        ).fetchone()

    finally:
        connection.close()


def add_site(
    name,
    url,
    visible=1,
):
    connection = get_db()

    try:
        row = connection.execute(
            """
            SELECT COALESCE(MAX(sort_order), 0) + 1 AS n
            FROM sites
            """
        ).fetchone()

        order_no = int(row["n"])

        cursor = connection.execute(
            """
            INSERT INTO sites(
                name,
                url,
                visible,
                sort_order,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                name,
                url,
                int(visible),
                order_no,
                utc_now(),
            ),
        )

        connection.commit()

        return cursor.lastrowid

    finally:
        connection.close()


def update_site(
    site_id,
    name=None,
    url=None,
    visible=None,
):
    fields = []
    values = []

    if name is not None:
        fields.append("name = ?")
        values.append(name)

    if url is not None:
        fields.append("url = ?")
        values.append(url)

    if visible is not None:
        fields.append("visible = ?")
        values.append(int(visible))

    if not fields:
        return

    values.append(site_id)

    connection = get_db()

    try:
        connection.execute(
            f"""
            UPDATE sites
            SET {", ".join(fields)}
            WHERE id = ?
            """,
            values,
        )

        connection.commit()

    finally:
        connection.close()


def delete_site(site_id):
    connection = get_db()

    try:
        connection.execute(
            "DELETE FROM sites WHERE id = ?",
            (site_id,),
        )

        connection.commit()

    finally:
        connection.close()


def reorder_sites(site_ids):
    connection = get_db()

    try:
        for order_no, site_id in enumerate(
            site_ids,
            1,
        ):
            connection.execute(
                """
                UPDATE sites
                SET sort_order = ?
                WHERE id = ?
                """,
                (
                    order_no,
                    site_id,
                ),
            )

        connection.commit()

    finally:
        connection.close()


# =========================================================
# TANITIM FONKSİYONLARI
# =========================================================

def get_promotion_by_command(command):
    command = normalize_site_command(command)

    connection = get_db()

    try:
        return connection.execute(
            """
            SELECT *
            FROM promotions
            WHERE command = ?
            """,
            (command,),
        ).fetchone()

    finally:
        connection.close()


def get_promotion(promo_id):
    connection = get_db()

    try:
        return connection.execute(
            """
            SELECT *
            FROM promotions
            WHERE id = ?
            """,
            (promo_id,),
        ).fetchone()

    finally:
        connection.close()


def get_promotions():
    connection = get_db()

    try:
        return connection.execute(
            """
            SELECT *
            FROM promotions
            ORDER BY id DESC
            """
        ).fetchall()

    finally:
        connection.close()


def save_promotion(
    command,
    text,
    image_file_id=None,
    buttons=None,
    promo_id=None,
):
    command = normalize_site_command(command)

    buttons_json = json.dumps(
        buttons or [],
        ensure_ascii=False,
    )

    connection = get_db()

    try:
        if promo_id:
            connection.execute(
                """
                UPDATE promotions
                SET
                    command = ?,
                    image_file_id = ?,
                    text = ?,
                    buttons_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    command,
                    image_file_id,
                    text,
                    buttons_json,
                    utc_now(),
                    promo_id,
                ),
            )

        else:
            now = utc_now()

            connection.execute(
                """
                INSERT INTO promotions(
                    command,
                    image_file_id,
                    text,
                    buttons_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    command,
                    image_file_id,
                    text,
                    buttons_json,
                    now,
                    now,
                ),
            )

        connection.commit()

    finally:
        connection.close()


def delete_promotion(promo_id):
    connection = get_db()

    try:
        connection.execute(
            "DELETE FROM promotions WHERE id = ?",
            (promo_id,),
        )

        connection.commit()

    finally:
        connection.close()


# =========================================================
# BUTONLAR
# =========================================================

def promotion_buttons_markup(buttons):
    rows = []

    for button in buttons:
        text = str(
            button.get(
                "text",
                "Link",
            )
        )[:64]

        url = str(
            button.get(
                "url",
                "",
            )
        )

        if valid_http_url(url):
            rows.append(
                [
                    InlineKeyboardButton(
                        text,
                        url=url,
                    )
                ]
            )

    if not rows:
        return None

    return InlineKeyboardMarkup(rows)


def site_menu_markup(sites):
    rows = []

    for site in sites:
        rows.append(
            [
                InlineKeyboardButton(
                    f"🌐 {site['name']}",
                    url=site["url"],
                )
            ]
        )

    if not rows:
        return None

    return InlineKeyboardMarkup(rows)


# =========================================================
# SITE ADMİN MENÜSÜ
# =========================================================

def site_admin_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ Site Ekle",
                    callback_data=SITE_ADMIN_PREFIX + "add",
                )
            ],
            [
                InlineKeyboardButton(
                    "✏️ Site Düzenle",
                    callback_data=SITE_ADMIN_PREFIX + "edit",
                )
            ],
            [
                InlineKeyboardButton(
                    "🗑️ Site Sil",
                    callback_data=SITE_ADMIN_PREFIX + "delete",
                )
            ],
            [
                InlineKeyboardButton(
                    "↕️ Site Sırası",
                    callback_data=SITE_ADMIN_PREFIX + "order",
                )
            ],
            [
                InlineKeyboardButton(
                    "📋 Siteleri Listele",
                    callback_data=SITE_ADMIN_PREFIX + "list",
                )
            ],
            [
                InlineKeyboardButton(
                    "➕ Tanıtım Ekle",
                    callback_data=SITE_ADMIN_PREFIX + "promo_add",
                )
            ],
            [
                InlineKeyboardButton(
                    "✏️ Tanıtım Düzenle",
                    callback_data=SITE_ADMIN_PREFIX + "promo_edit",
                )
            ],
            [
                InlineKeyboardButton(
                    "🗑️ Tanıtım Sil",
                    callback_data=SITE_ADMIN_PREFIX + "promo_delete",
                )
            ],
            [
                InlineKeyboardButton(
                    "📋 Tanıtımları Listele",
                    callback_data=SITE_ADMIN_PREFIX + "promo_list",
                )
            ],
        ]
    )


def site_admin_text():
    return (
        "⚙️ <b>HEROPRIME SİTE YÖNETİMİ</b>\n\n"
        "🌐 Buradan siteleri yönetebilirsin.\n"
        "📢 Tanıtım komutlarını oluşturabilirsin.\n\n"
        "<b>SİTE SİSTEMİ</b>\n"
        "• Site ekleme\n"
        "• Site düzenleme\n"
        "• Site silme\n"
        "• Site sıralama\n"
        "• Görünürlük kontrolü\n\n"
        "<b>TANITIM SİSTEMİ</b>\n"
        "Tanıtımlar örneğin:\n"
        "<code>!raconbet</code>\n"
        "<code>.raconbet</code>\n"
        "<code>/raconbet</code>\n"
        "şeklinde kullanılabilir."
    )


# =========================================================
# /SITE
# =========================================================

async def site_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message

    if not message:
        return

    sites = get_sites(True)

    if not sites:
        await message.reply_text(
            "🌐 <b>SİTELER</b>\n\n"
            "Henüz site eklenmemiş.",
            parse_mode="HTML",
        )
        return

    await message.reply_text(
        "🌐 <b>HEROPRIME SİTELER</b>\n\n"
        "Bir site seç:",
        parse_mode="HTML",
        reply_markup=site_menu_markup(sites),
    )


async def site_alias_command(
    update,
    context,
):
    await site_command(
        update,
        context,
    )


# =========================================================
# /SITEYONETIM
# =========================================================

async def site_admin_command(
    update,
    context,
):
    message = update.effective_message
    user = update.effective_user

    if (
        not message
        or not user
        or not is_admin(user.id)
        or message.chat.type != "private"
    ):
        return

    context.user_data.clear()

    await message.reply_text(
        site_admin_text(),
        parse_mode="HTML",
        reply_markup=site_admin_keyboard(),
    )


# =========================================================
# SITE ADMİN CALLBACK
# =========================================================

async def site_admin_callback(
    update,
    context,
):
    query = update.callback_query

    if not query:
        return

    user = query.from_user

    if not user or not is_admin(user.id):
        await query.answer(
            "❌ Yetkin yok.",
            show_alert=True,
        )
        return

    data = query.data or ""

    action = data.replace(
        SITE_ADMIN_PREFIX,
        "",
        1,
    )

    await query.answer()

    # -----------------------------------------------------
    # PANEL
    # -----------------------------------------------------

    if action == "panel":
        await query.message.reply_text(
            site_admin_text(),
            parse_mode="HTML",
            reply_markup=site_admin_keyboard(),
        )
        return

    # -----------------------------------------------------
    # SITE EKLE
    # -----------------------------------------------------

    if action == "add":
        context.user_data.clear()

        context.user_data["site_flow"] = {
            "step": "name"
        }

        await query.message.reply_text(
            "➕ <b>Site Ekle</b>\n\n"
            "Site adını gönder.\n\n"
            "Örnek:\n"
            "<code>RACONBET</code>\n\n"
            "/iptal ile iptal edebilirsin.",
            parse_mode="HTML",
        )
        return

    # -----------------------------------------------------
    # SITE LİSTELE
    # -----------------------------------------------------

    if action == "list":
        sites = get_sites(False)

        if not sites:
            await query.message.reply_text(
                "📋 Site listesi boş."
            )
            return

        lines = []

        for i, site in enumerate(
            sites,
            1,
        ):
            status = (
                "🟢"
                if site["visible"]
                else "⚪"
            )

            lines.append(
                f"{i}. <b>{escape(site['name'])}</b> "
                f"{status}\n"
                f"   ID: <code>{site['id']}</code>\n"
                f"   {escape(site['url'])}"
            )

        await query.message.reply_text(
            "📋 <b>SİTELER</b>\n\n"
            + "\n\n".join(lines),
            parse_mode="HTML",
        )
        return

    # -----------------------------------------------------
    # SITE DÜZENLE / SİL
    # -----------------------------------------------------

    if action in (
        "edit",
        "delete",
    ):
        sites = get_sites(False)

        if not sites:
            await query.message.reply_text(
                "Henüz site yok."
            )
            return

        rows = []

        for site in sites:
            rows.append(
                [
                    InlineKeyboardButton(
                        site["name"],
                        callback_data=(
                            f"{SITE_ADMIN_PREFIX}"
                            f"{action}_id:"
                            f"{site['id']}"
                        ),
                    )
                ]
            )

        rows.append(
            [
                InlineKeyboardButton(
                    "⬅️ Geri",
                    callback_data=(
                        SITE_ADMIN_PREFIX
                        + "panel"
                    ),
                )
            ]
        )

        await query.message.reply_text(
            "Site seç:",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    # -----------------------------------------------------
    # SITE SİL
    # -----------------------------------------------------

    if action.startswith("delete_id:"):
        try:
            site_id = int(
                action.split(
                    ":",
                    1,
                )[1]
            )
        except ValueError:
            await query.message.reply_text(
                "❌ Geçersiz site."
            )
            return

        delete_site(site_id)

        await query.message.reply_text(
            "✅ Site silindi."
        )
        return

    # -----------------------------------------------------
    # SITE DÜZENLE
    # -----------------------------------------------------

    if action.startswith("edit_id:"):
        try:
            site_id = int(
                action.split(
                    ":",
                    1,
                )[1]
            )
        except ValueError:
            await query.message.reply_text(
                "❌ Geçersiz site."
            )
            return

        site = get_site(site_id)

        if not site:
            await query.message.reply_text(
                "❌ Site bulunamadı."
            )
            return

        context.user_data.clear()

        context.user_data["site_flow"] = {
            "step": "edit_name",
            "id": site_id,
        }

        await query.message.reply_text(
            "✏️ <b>Site Düzenle</b>\n\n"
            f"Mevcut ad: "
            f"<b>{escape(site['name'])}</b>\n\n"
            "Yeni site adını gönder.",
            parse_mode="HTML",
        )
        return

    # -----------------------------------------------------
    # SITE SIRALAMA
    # -----------------------------------------------------

    if action == "order":
        sites = get_sites(False)

        if len(sites) < 2:
            await query.message.reply_text(
                "↕️ Sıralama için en az 2 site gerekli."
            )
            return

        context.user_data.clear()

        context.user_data["site_flow"] = {
            "step": "order"
        }

        ids = ", ".join(
            str(site["id"])
            for site in sites
        )

        await query.message.reply_text(
            "↕️ <b>SİTE SIRASI</b>\n\n"
            f"Mevcut ID sırası:\n"
            f"<code>{ids}</code>\n\n"
            "Yeni sırayı virgülle gönder.\n\n"
            "Örnek:\n"
            "<code>3,1,2</code>",
            parse_mode="HTML",
        )
        return

    # -----------------------------------------------------
    # TANITIM EKLE
    # -----------------------------------------------------

    if action == "promo_add":
        context.user_data.clear()

        context.user_data["promo_flow"] = {
            "step": "command",
            "buttons": [],
        }

        await query.message.reply_text(
            "➕ <b>Tanıtım Ekle</b>\n\n"
            "Komut adını gönder.\n\n"
            "Örnek:\n"
            "<code>!raconbet</code>\n\n"
            "! . / fark etmez.",
            parse_mode="HTML",
        )
        return

    # -----------------------------------------------------
    # TANITIM DÜZENLE / SİL
    # -----------------------------------------------------

    if action in (
        "promo_edit",
        "promo_delete",
    ):
        promos = get_promotions()

        if not promos:
            await query.message.reply_text(
                "Henüz tanıtım yok."
            )
            return

        rows = []

        for promo in promos:
            rows.append(
                [
                    InlineKeyboardButton(
                        "!"
                        + promo["command"],
                        callback_data=(
                            f"{SITE_ADMIN_PREFIX}"
                            f"{action}_id:"
                            f"{promo['id']}"
                        ),
                    )
                ]
            )

        await query.message.reply_text(
            "Tanıtım seç:",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    # -----------------------------------------------------
    # TANITIM SİL
    # -----------------------------------------------------

    if action.startswith("promo_delete_id:"):
        try:
            promo_id = int(
                action.split(
                    ":",
                    1,
                )[1]
            )
        except ValueError:
            await query.message.reply_text(
                "❌ Geçersiz tanıtım."
            )
            return

        delete_promotion(promo_id)

        await query.message.reply_text(
            "✅ Tanıtım silindi."
        )
        return

    # -----------------------------------------------------
    # TANITIM DÜZENLE
    # -----------------------------------------------------

    if action.startswith("promo_edit_id:"):
        try:
            promo_id = int(
                action.split(
                    ":",
                    1,
                )[1]
            )
        except ValueError:
            await query.message.reply_text(
                "❌ Geçersiz tanıtım."
            )
            return

        promo = get_promotion(promo_id)

        if not promo:
            await query.message.reply_text(
                "❌ Tanıtım bulunamadı."
            )
            return

        context.user_data.clear()

        context.user_data["promo_flow"] = {
            "step": "edit_text",
            "id": promo["id"],
            "command": promo["command"],
            "buttons": json.loads(
                promo["buttons_json"]
                or "[]"
            ),
            "image": promo["image_file_id"],
        }

        await query.message.reply_text(
            "✏️ <b>Tanıtım Düzenle</b>\n\n"
            f"Komut: <code>!{promo['command']}</code>\n\n"
            "Yeni tanıtım metnini gönder.\n\n"
            "Mevcut metin:\n"
            f"{escape(promo['text'])}",
            parse_mode="HTML",
        )
        return

    # -----------------------------------------------------
    # TANITIM LİSTELE
    # -----------------------------------------------------

    if action == "promo_list":
        promos = get_promotions()

        if not promos:
            await query.message.reply_text(
                "📋 Tanıtım listesi boş."
            )
            return

        lines = []

        for i, promo in enumerate(
            promos,
            1,
        ):
            media = (
                "🖼️ Görselli"
                if promo["image_file_id"]
                else "📝 Metin"
            )

            lines.append(
                f"{i}. <code>!{promo['command']}</code> "
                f"— {media}"
            )

        await query.message.reply_text(
            "📋 <b>TANITIMLAR</b>\n\n"
            + "\n".join(lines),
            parse_mode="HTML",
        )
        return


# =========================================================
# SITE ADMIN CALLBACK - EK AKIŞLAR
# =========================================================

async def site_admin_callback_extended(
    update,
    context,
):
    query = update.callback_query

    if not query:
        return

    user = query.from_user

    if not user or not is_admin(user.id):
        await query.answer(
            "❌ Yetkin yok.",
            show_alert=True,
        )
        return

    data = query.data or ""

    # -----------------------------------------------------
    # YENİ SITE GÖRÜNÜRLÜĞÜ
    # -----------------------------------------------------

    if data.startswith(
        SITE_ADMIN_PREFIX + "vis:"
    ):
        flow = context.user_data.get(
            "site_flow"
        )

        if not flow:
            await query.answer(
                "❌ İşlem süresi doldu.",
                show_alert=True,
            )
            return

        visible = 1 if data.endswith(":1") else 0

        add_site(
            flow["name"],
            flow["url"],
            visible,
        )

        context.user_data.clear()

        await query.answer(
            "Kaydedildi."
        )

        await query.message.reply_text(
            "✅ Site başarıyla eklendi."
        )

        return

    # -----------------------------------------------------
    # DÜZENLENEN SITE GÖRÜNÜRLÜĞÜ
    # -----------------------------------------------------

    if data.startswith(
        SITE_ADMIN_PREFIX + "editvis:"
    ):
        flow = context.user_data.get(
            "site_flow"
        )

        if not flow:
            await query.answer(
                "❌ İşlem süresi doldu.",
                show_alert=True,
            )
            return

        visible = 1 if data.endswith(":1") else 0

        update_site(
            flow["id"],
            flow["name"],
            flow["url"],
            visible,
        )

        context.user_data.clear()

        await query.answer(
            "Güncellendi."
        )

        await query.message.reply_text(
            "✅ Site güncellendi."
        )

        return

    # -----------------------------------------------------
    # TANITIM GÖRSELİ
    # -----------------------------------------------------

    if data == SITE_ADMIN_PREFIX + "p_skip:0":
        flow = context.user_data.get(
            "promo_flow"
        )

        if not flow:
            await query.answer(
                "❌ İşlem süresi doldu.",
                show_alert=True,
            )
            return

        flow["step"] = "image"

        await query.answer()

        await query.message.reply_text(
            "🖼️ Şimdi tanıtım görselini gönder."
        )

        return

    # -----------------------------------------------------
    # TANITIM GÖRSELİNİ GEÇ
    # -----------------------------------------------------

    if data == SITE_ADMIN_PREFIX + "p_skip:1":
        flow = context.user_data.get(
            "promo_flow"
        )

        if not flow:
            await query.answer(
                "❌ İşlem süresi doldu.",
                show_alert=True,
            )
            return

        flow["step"] = "text"

        await query.answer()

        await query.message.reply_text(
            "📝 Tanıtım metnini gönder."
        )

        return

    # -----------------------------------------------------
    # BUTON EKLE
    # -----------------------------------------------------

    if data == SITE_ADMIN_PREFIX + "btn_add":
        flow = context.user_data.get(
            "promo_flow"
        )

        if not flow:
            await query.answer(
                "❌ İşlem süresi doldu.",
                show_alert=True,
            )
            return

        flow["step"] = "button_text"

        await query.answer()

        await query.message.reply_text(
            "🔘 Buton yazısını gönder."
        )

        return

    # -----------------------------------------------------
    # TANITIM KAYDET
    # -----------------------------------------------------

    if data == SITE_ADMIN_PREFIX + "promo_save":
        flow = context.user_data.get(
            "promo_flow"
        )

        if (
            not flow
            or not flow.get("command")
            or not flow.get("text")
        ):
            await query.answer(
                "❌ Eksik bilgi.",
                show_alert=True,
            )
            return

        try:
            save_promotion(
                flow["command"],
                flow["text"],
                flow.get("image"),
                flow.get("buttons", []),
                flow.get("id"),
            )

        except sqlite3.IntegrityError:
            await query.answer(
                "❌ Bu komut zaten kullanılıyor.",
                show_alert=True,
            )
            return

        context.user_data.clear()

        await query.answer(
            "Kaydedildi."
        )

        await query.message.reply_text(
            "✅ Tanıtım başarıyla kaydedildi."
        )

        return

    await query.answer()


# =========================================================
# SITE ADMIN TEXT FLOW
# =========================================================

async def site_admin_flow_message(
    update,
    context,
):
    message = update.effective_message
    user = update.effective_user

    if (
        not message
        or not user
        or not is_admin(user.id)
        or message.chat.type != "private"
    ):
        return False

    flow = context.user_data.get(
        "site_flow"
    )

    if not flow:
        return False

    text = (
        message.text
        or ""
    ).strip()

    if text == "/iptal":
        context.user_data.clear()

        await message.reply_text(
            "❌ İşlem iptal edildi."
        )

        return True

    step = flow.get("step")

    # -----------------------------------------------------
    # SITE ADI
    # -----------------------------------------------------

    if step == "name":
        if (
            not text
            or len(text) > SITE_MAX_NAME
        ):
            await message.reply_text(
                "❌ Geçerli bir site adı gönder."
            )
            return True

        flow["name"] = text
        flow["step"] = "url"

        await message.reply_text(
            "🔗 Site linkini gönder.\n\n"
            "Örnek:\n"
            "<code>https://site.com</code>",
            parse_mode="HTML",
        )

        return True

    # -----------------------------------------------------
    # SITE URL
    # -----------------------------------------------------

    if step == "url":
        if not valid_http_url(text):
            await message.reply_text(
                "❌ Geçerli bir http/https linki gönder."
            )
            return True

        flow["url"] = text
        flow["step"] = "visible"

        await message.reply_text(
            "👁️ /site menüsünde görünsün mü?",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Evet",
                            callback_data=(
                                SITE_ADMIN_PREFIX
                                + "vis:1"
                            ),
                        ),
                        InlineKeyboardButton(
                            "❌ Hayır",
                            callback_data=(
                                SITE_ADMIN_PREFIX
                                + "vis:0"
                            ),
                        ),
                    ]
                ]
            ),
        )

        return True

    # -----------------------------------------------------
    # DÜZENLEME - İSİM
    # -----------------------------------------------------

    if step == "edit_name":
        if (
            not text
            or len(text) > SITE_MAX_NAME
        ):
            await message.reply_text(
                "❌ Geçerli bir site adı gönder."
            )
            return True

        flow["name"] = text
        flow["step"] = "edit_url"

        await message.reply_text(
            "🔗 Yeni site linkini gönder."
        )

        return True

    # -----------------------------------------------------
    # DÜZENLEME - URL
    # -----------------------------------------------------

    if step == "edit_url":
        if not valid_http_url(text):
            await message.reply_text(
                "❌ Geçerli bir link gönder."
            )
            return True

        flow["url"] = text
        flow["step"] = "edit_visible"

        await message.reply_text(
            "👁️ /site görünürlüğü?",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🟢 Açık",
                            callback_data=(
                                SITE_ADMIN_PREFIX
                                + "editvis:1"
                            ),
                        ),
                        InlineKeyboardButton(
                            "⚪ Kapalı",
                            callback_data=(
                                SITE_ADMIN_PREFIX
                                + "editvis:0"
                            ),
                        ),
                    ]
                ]
            ),
        )

        return True

    # -----------------------------------------------------
    # SIRALAMA
    # -----------------------------------------------------

    if step == "order":
        try:
            ids = [
                int(x.strip())
                for x in text.split(",")
                if x.strip()
            ]

        except ValueError:
            await message.reply_text(
                "❌ ID formatı hatalı."
            )
            return True

        sites = get_sites(False)

        valid = {
            site["id"]
            for site in sites
        }

        if (
            set(ids) != valid
            or len(ids) != len(valid)
        ):
            await message.reply_text(
                "❌ Tüm site ID'lerini "
                "birer kez sıralamalısın."
            )
            return True

        reorder_sites(ids)

        context.user_data.clear()

        await message.reply_text(
            "✅ Site sırası güncellendi."
        )

        return True

    return False


# =========================================================
# TANITIM ADMIN PHOTO
# =========================================================

async def site_admin_photo(
    update,
    context,
):
    message = update.effective_message
    user = update.effective_user

    if (
        not message
        or not user
        or not is_admin(user.id)
        or message.chat.type != "private"
    ):
        return False

    flow = context.user_data.get(
        "promo_flow"
    )

    if (
        not flow
        or flow.get("step") != "image"
    ):
        return False

    if not message.photo:
        return False

    flow["image"] = (
        message.photo[-1].file_id
    )

    flow["step"] = "text"

    await message.reply_text(
        "📝 Tanıtım metnini gönder.\n\n"
        "HTML gerekmez."
    )

    return True


# =========================================================
# TANITIM TEXT FLOW
# =========================================================

async def site_admin_promo_flow(
    update,
    context,
):
    message = update.effective_message
    user = update.effective_user

    if (
        not message
        or not user
        or not is_admin(user.id)
        or message.chat.type != "private"
    ):
        return False

    flow = context.user_data.get(
        "promo_flow"
    )

    if not flow:
        return False

    text = (
        message.text
        or ""
    ).strip()

    if text == "/iptal":
        context.user_data.clear()

        await message.reply_text(
            "❌ İşlem iptal edildi."
        )

        return True

    step = flow.get("step")

    # -----------------------------------------------------
    # KOMUT
    # -----------------------------------------------------

    if step == "command":
        command = normalize_site_command(
            text
        )

        if not command:
            await message.reply_text(
                "❌ Geçerli bir komut gönder.\n\n"
                "Örnek: <code>!raconbet</code>",
                parse_mode="HTML",
            )
            return True

        old = get_promotion_by_command(
            command
        )

        if (
            old
            and old["id"] != flow.get("id")
        ):
            await message.reply_text(
                "❌ Bu tanıtım komutu zaten kullanılıyor."
            )
            return True

        flow["command"] = command
        flow["step"] = "image"

        await message.reply_text(
            "🖼️ Tanıtıma görsel eklemek ister misin?",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🖼️ Görsel Ekle",
                            callback_data=(
                                SITE_ADMIN_PREFIX
                                + "p_skip:0"
                            ),
                        ),
                        InlineKeyboardButton(
                            "⏭️ Görseli Geç",
                            callback_data=(
                                SITE_ADMIN_PREFIX
                                + "p_skip:1"
                            ),
                        ),
                    ]
                ]
            ),
        )

        return True

    # -----------------------------------------------------
    # TANITIM METNİ
    # -----------------------------------------------------

    if step in (
        "text",
        "edit_text",
    ):
        if (
            not text
            or len(text) > SITE_MAX_TEXT
        ):
            await message.reply_text(
                "❌ Metin boş olamaz ve "
                "3500 karakteri geçemez."
            )
            return True

        flow["text"] = escape(text)
        flow["step"] = "buttons"

        await message.reply_text(
            "🔘 Tanıtıma buton ekleyebilirsin.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "➕ Buton Ekle",
                            callback_data=(
                                SITE_ADMIN_PREFIX
                                + "btn_add"
                            ),
                        ),
                        InlineKeyboardButton(
                            "💾 Kaydet",
                            callback_data=(
                                SITE_ADMIN_PREFIX
                                + "promo_save"
                            ),
                        ),
                    ]
                ]
            ),
        )

        return True

    # -----------------------------------------------------
    # BUTON ADI
    # -----------------------------------------------------

    if step == "button_text":
        if (
            not text
            or len(text) > 64
        ):
            await message.reply_text(
                "❌ Buton metni "
                "64 karakteri geçmesin."
            )
            return True

        flow["button_text"] = text
        flow["step"] = "button_url"

        await message.reply_text(
            "🔗 Bu butonun URL'sini gönder."
        )

        return True

    # -----------------------------------------------------
    # BUTON URL
    # -----------------------------------------------------

    if step == "button_url":
        if not valid_http_url(text):
            await message.reply_text(
                "❌ Geçerli bir URL gönder."
            )
            return True

        button_text = flow.pop(
            "button_text"
        )

        flow.setdefault(
            "buttons",
            [],
        ).append(
            {
                "text": button_text,
                "url": text,
            }
        )

        flow["step"] = "buttons"

        await message.reply_text(
            "✅ Buton eklendi.\n\n"
            "Başka buton ekleyebilir veya kaydedebilirsin.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "➕ Buton Ekle",
                            callback_data=(
                                SITE_ADMIN_PREFIX
                                + "btn_add"
                            ),
                        ),
                        InlineKeyboardButton(
                            "💾 Kaydet",
                            callback_data=(
                                SITE_ADMIN_PREFIX
                                + "promo_save"
                            ),
                        ),
                    ]
                ]
            ),
        )

        return True

    return False


# =========================================================
# TANITIM KOMUTLARI
# =========================================================

async def run_promotion_command(
    update,
    context,
):
    message = update.effective_message

    if (
        not message
        or not message.text
    ):
        return

    match = re.match(
        r"^\s*([!./])([A-Za-z0-9_]+)(?:\s|$)",
        message.text,
    )

    if not match:
        return

    command = normalize_site_command(
        match.group(2)
    )

    reserved_commands = {
        "site",
        "siteyonetim",
        "start",
        "myid",
        "iptal",
    }

    if command in reserved_commands:
        return

    promo = get_promotion_by_command(
        command
    )

    if not promo:
        return

    buttons = json.loads(
        promo["buttons_json"]
        or "[]"
    )

    markup = promotion_buttons_markup(
        buttons
    )

    text = promo["text"]

    if promo["image_file_id"]:
        await message.reply_photo(
            photo=promo["image_file_id"],
            caption=text,
            parse_mode="HTML",
            reply_markup=markup,
        )

    else:
        await message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=markup,
        )


# =========================================================
# /START
# =========================================================

async def start_command(
    update,
    context,
):
    message = update.effective_message
    user = update.effective_user

    if (
        not message
        or not user
        or message.chat.type != "private"
    ):
        return

    if not is_admin(user.id):
        await message.reply_text(
            "👋 <b>Hoş geldin!</b>\n\n"
            "🤖 HEROPRIME Site Botu aktif.\n\n"
            "🌐 Siteleri görmek için "
            "<code>/site</code> kullanabilirsin.\n"
            "🆔 <code>/myid</code>",
            parse_mode="HTML",
        )
        return

    await message.reply_text(
        "🤖 <b>HEROPRIME SİTE BOTU</b>\n\n"
        "✅ Bot aktif.\n\n"
        "🌐 <b>Site sistemi</b>\n"
        "/site\n"
        "/siteyonetim\n\n"
        "📢 <b>Tanıtım sistemi</b>\n"
        "Özel tanıtım komutlarını "
        "site yönetiminden oluşturabilirsin.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⚙️ Site Yönetimi",
                        callback_data=(
                            SITE_ADMIN_PREFIX
                            + "panel"
                        ),
                    )
                ]
            ]
        ),
    )


# =========================================================
# /MYID
# =========================================================

async def my_id(
    update,
    context,
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
        f"Kullanıcı adı: {escape(username)}\n"
        f"Ad: {escape(user.full_name)}",
        parse_mode="HTML",
    )


# =========================================================
# HATA / WEBHOOK
# =========================================================

async def error_handler(
    update,
    context,
):
    logger.error(
        "Telegram bot hatası: %s",
        context.error,
        exc_info=context.error,
    )


async def clear_old_webhook(
    application,
):
    try:
        info = await application.bot.get_webhook_info()

        if info.url:
            await application.bot.delete_webhook(
                drop_pending_updates=True
            )

            logger.info(
                "Eski webhook temizlendi."
            )

    except Exception as error:
        logger.warning(
            "Webhook temizlenemedi: %s",
            error,
        )


# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN bulunamadı. "
            "Railway Variables içine BOT_TOKEN ekle."
        )

    if not ADMIN_IDS:
        raise RuntimeError(
            "ADMIN_IDS bulunamadı. "
            "Railway Variables içine ADMIN_IDS ekle."
        )

    init_database()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(clear_old_webhook)
        .build()
    )

    # -----------------------------------------------------
    # TEMEL KOMUTLAR
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # SITE
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "site",
            site_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "siteyonetim",
            site_admin_command,
        )
    )

    # !site / .site
    application.add_handler(
        MessageHandler(
            filters.Regex(
                r"^\s*[!.]site\s*$"
            ),
            site_alias_command,
        )
    )

    # -----------------------------------------------------
    # SITE ADMIN CALLBACK
    # -----------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            site_admin_callback_extended,
            pattern=(
                r"^siteadmin:"
                r"(vis:|editvis:|p_skip:|"
                r"btn_add$|promo_save$)"
            ),
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            site_admin_callback,
            pattern=r"^siteadmin:",
        )
    )

    # -----------------------------------------------------
    # SITE ADMIN GÖRSEL
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.PHOTO
            & filters.ChatType.PRIVATE,
            site_admin_photo,
            ),
        group=2,
    )

    # -----------------------------------------------------
    # SITE ADMIN METİN
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.ChatType.PRIVATE,
            site_admin_flow_message,
        ),
        group=2,
    )

    # -----------------------------------------------------
    # TANITIM ADMIN METİN AKIŞI
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.ChatType.PRIVATE,
            site_admin_promo_flow,
        ),
        group=3,
    )

    # -----------------------------------------------------
    # TANITIM KOMUTLARI
    # !raconbet
    # .raconbet
    # /raconbet
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            run_promotion_command,
        ),
        group=4,
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "HEROPRIME Site Botu başlatılıyor..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        bootstrap_retries=5,
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()
