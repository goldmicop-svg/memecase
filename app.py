"""MEME CASE — серверная логика демо-приложения.

Учётные записи и весь игровой прогресс (монеты, инвентарь, число открытых
кейсов) хранятся в локальном SQLite-файле ``meme_case.db`` — отдельная
строка на каждого пользователя. Это гарантирует, что баланс и инвентарь
у каждого аккаунта свои и не "слипаются" между пользователями при
перезапуске сервера или при нескольких воркерах процесса.
"""

import json
import os
import random
import re
import sqlite3
import uuid
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
DATABASE = BASE_DIR / "meme_case.db"
ALLOWED_AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

app = Flask(__name__)
app.secret_key = os.environ.get("MEME_CASE_SECRET", "meme-case-demo-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024


# ======================================================================
# ИГРОВЫЕ ДАННЫЕ
# ======================================================================

RARITY = {
    "common": {"label": "Обычный", "color": "var(--r-common)"},
    "rare": {"label": "Редкий", "color": "var(--r-rare)"},
    "epic": {"label": "Эпический", "color": "var(--r-epic)"},
    "legendary": {"label": "Легендарный", "color": "var(--r-legendary)"},
}
RARITY_WEIGHT = {"common": 60, "rare": 25, "epic": 12, "legendary": 3}

ITEM_POOL = [
    {"id": "sticker_popcat", "name": "Стикер «Popcat»", "icon": "🐱", "rarity": "common", "value": 90},
    {"id": "cap_cheems", "name": "Кепка «Cheems»", "icon": "🧢", "rarity": "common", "value": 120},
    {"id": "pistol_pepe", "name": "Пистолет «Pepe Blue»", "icon": "🔫", "rarity": "common", "value": 150},
    {"id": "badge_frog", "name": "Значок «Frog Squad»", "icon": "🐸", "rarity": "common", "value": 180},
    {"id": "mask_troll", "name": "Маска «Trollface»", "icon": "🎭", "rarity": "rare", "value": 350},
    {"id": "coin_chad", "name": "Монета «Chad»", "icon": "🪙", "rarity": "rare", "value": 400},
    {"id": "bandana_doge", "name": "Бандана «Doge Style»", "icon": "🐶", "rarity": "rare", "value": 460},
    {"id": "rocket_cat", "name": "Скин «Rocket Cat»", "icon": "🚀", "rarity": "epic", "value": 750},
    {"id": "hoodie_wojak", "name": "Скин «Wojak Hoodie»", "icon": "🧥", "rarity": "epic", "value": 800},
    {"id": "gun_gigachad", "name": "Пистолет «Gigachad»", "icon": "💪", "rarity": "epic", "value": 900},
    {"id": "knife_doge", "name": "Нож «Golden Doge»", "icon": "🔪", "rarity": "legendary", "value": 1200},
    {"id": "knife_pepe", "name": "Нож «Pepe Gold»", "icon": "🔪", "rarity": "legendary", "value": 1400},
    {"id": "gem_frog", "name": "Скин «Gem Frog»", "icon": "💎", "rarity": "legendary", "value": 1500},
    {"id": "crown_doge", "name": "Корона «Doge King»", "icon": "👑", "rarity": "legendary", "value": 2000},
]

# Все изображения из переданной папки стали отдельными персонажами.
CHARACTER_IMAGES = [
    "5278675408956104248.jpg", "5278675408956104249.jpg", "5278675408956104250.jpg",
    "5278675408956104251.jpg", "5278675408956104252.jpg", "5278675408956104253.jpg",
    "5278675408956104254.jpg", "5278675408956104255.jpg", "5278675408956104256.jpg",
    "5278675408956104257.jpg", "5278675408956104258.jpg", "5278675408956104259.jpg",
    "5278675408956104260.jpg", "5278675408956104261.jpg", "5278675408956104262.jpg",
    "5278675408956104263.jpg", "5278675408956104264.jpg", "5278675408956104265.jpg",
    "5278675408956104266.jpg", "5278675408956104267.jpg", "5278675408956104268.jpg",
    "5278675408956104269.jpg", "5278675408956104279.jpg", "5278675408956104280.jpg",
    "5278675408956104281.jpg", "5278675408956104282.jpg",
]
CHARACTER_RARITIES = [
    "common", "common", "common", "common", "common", "common", "common", "common",
    "rare", "rare", "rare", "rare", "rare", "rare", "rare", "epic", "epic", "epic",
    "epic", "epic", "epic", "epic", "legendary", "legendary", "legendary", "legendary",
]
CHARACTER_VALUES = [
    110, 130, 150, 170, 190, 210, 230, 250, 340, 390, 430, 470, 520,
    570, 620, 760, 830, 910, 990, 1080, 1170, 1260, 1450, 1650, 1850, 2200,
]
for number, filename in enumerate(CHARACTER_IMAGES, start=1):
    ITEM_POOL.append({
        "id": f"character_{number}", "name": f"Персонаж #{number:02d}", "icon": "🧑",
        "image": f"/static/characters/{filename}", "rarity": CHARACTER_RARITIES[number - 1],
        "value": CHARACTER_VALUES[number - 1],
    })

CASES = [
    {"id": "cyberpunk", "name": "«КИБЕРПАНК»", "price": 299, "color": "#8B5CFF", "icon": "🟪"},
    {"id": "matrix", "name": "«МАТРИЦА»", "price": 450, "color": "#33D69F", "icon": "🟩"},
    {"id": "neon", "name": "«НЕОН»", "price": 150, "color": "#FF6FD8", "icon": "🟫"},
    {"id": "shadow", "name": "«ТЕНЬ»", "price": 99, "color": "#7B7EA8", "icon": "⬛"},
    {"id": "retro", "name": "«РЕТРО»", "price": 190, "color": "#FF9A3D", "icon": "🟧"},
    {"id": "classic", "name": "«КЛАССИКА»", "price": 350, "color": "#FFD76A", "icon": "🟨"},
]
COIN_PACKS = [
    {"coins": 500, "price": "99 M"}, {"coins": 1500, "price": "249 M"},
    {"coins": 5000, "price": "699 M"}, {"coins": 12000, "price": "1490 M"},
]
START_ITEM_IDS = ["pistol_pepe", "mask_troll"]


# ======================================================================
# УЧЁТНЫЕ ЗАПИСИ
# ======================================================================

def db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                is_banned INTEGER NOT NULL DEFAULT 0,
                avatar_path TEXT,
                coins INTEGER NOT NULL DEFAULT 51240,
                cases_opened INTEGER NOT NULL DEFAULT 0,
                inventory TEXT
            )
        """)
        # Мягкая миграция на случай, если файл базы создан предыдущей версией
        # приложения (без колонок прогресса) — тогда прогресс жил только в
        # памяти процесса и "слипался" при перезапуске или под несколькими
        # воркерами. Теперь у каждого аккаунта своя строка в SQLite.
        existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        for column, definition in (
            ("coins", "INTEGER NOT NULL DEFAULT 51240"),
            ("cases_opened", "INTEGER NOT NULL DEFAULT 0"),
            ("inventory", "TEXT"),
        ):
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")


def get_user(user_id):
    with db_connection() as conn:
        return conn.execute(
            "SELECT id, username, password_hash, is_admin, is_banned, avatar_path, coins, cases_opened, inventory FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()


def user_public(user):
    return {"id": user["id"], "username": user["username"], "is_admin": bool(user["is_admin"]), "avatar_url": user["avatar_path"]}


def active_user():
    user_id = session.get("user_id")
    if not user_id:
        return None, "auth_required"
    user = get_user(user_id)
    if not user:
        session.clear()
        return None, "auth_required"
    if user["is_banned"]:
        session.clear()
        return None, "banned"
    return user, None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user, error = active_user()
        if error:
            return jsonify({"error": error}), 403 if error == "banned" else 401
        return view(user, *args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(user, *args, **kwargs):
        if not user["is_admin"]:
            return jsonify({"error": "admin_required"}), 403
        return view(user, *args, **kwargs)
    return wrapped


def valid_username(username):
    return bool(re.fullmatch(r"[\w-]{3,24}", username, flags=re.UNICODE))


def looks_like_image(file, extension):
    """Быстрая проверка сигнатуры, чтобы не сохранять произвольный файл под .jpg."""
    header = file.stream.read(12)
    file.stream.seek(0)
    signatures = {
        "jpg": header.startswith(b"\xff\xd8\xff"),
        "jpeg": header.startswith(b"\xff\xd8\xff"),
        "png": header.startswith(b"\x89PNG\r\n\x1a\n"),
        "gif": header.startswith((b"GIF87a", b"GIF89a")),
        "webp": header.startswith(b"RIFF") and header[8:12] == b"WEBP",
    }
    return signatures.get(extension, False)


# ======================================================================
# ИГРОВАЯ ЛОГИКА
# ======================================================================

def item_by_id(item_id):
    return next((item for item in ITEM_POOL if item["id"] == item_id), None)


def make_instance(item_template):
    inst = dict(item_template)
    inst["instance_id"] = str(uuid.uuid4())
    return inst


def weighted_random_item():
    total = sum(RARITY_WEIGHT[item["rarity"]] for item in ITEM_POOL)
    roll = random.uniform(0, total)
    for item in ITEM_POOL:
        roll -= RARITY_WEIGHT[item["rarity"]]
        if roll <= 0:
            return item
    return ITEM_POOL[0]


def find_nearest_item(value):
    return min(ITEM_POOL, key=lambda item: abs(item["value"] - value))


def find_upgrade_result(input_item, target_value):
    """Предмет на выходе успешного апгрейда обязан стоить дороже входного —
    иначе игрок "выигрывает" и получает точно тот же предмет обратно."""
    candidates = [item for item in ITEM_POOL if item["value"] > input_item["value"]]
    if not candidates:
        return None
    return min(candidates, key=lambda item: abs(item["value"] - target_value))


def has_upgrade_target(item):
    return any(pool_item["value"] > item["value"] for pool_item in ITEM_POOL)


def new_game_state():
    return {"coins": 51240, "cases_opened": 0, "inventory": [make_instance(item_by_id(item_id)) for item_id in START_ITEM_IDS]}


def get_state(user):
    """Прогресс хранится в собственной строке пользователя в SQLite —
    у каждого аккаунта отдельные монеты и инвентарь, никакой общей памяти
    между пользователями или воркерами процесса."""
    if user["inventory"] is None:
        # Первый заход этого аккаунта — создаём стартовый инвентарь и сохраняем его.
        state = {
            "coins": user["coins"] if user["coins"] is not None else 51240,
            "cases_opened": user["cases_opened"] or 0,
            "inventory": [make_instance(item_by_id(item_id)) for item_id in START_ITEM_IDS],
        }
        save_state(user["id"], state)
        return state
    return {
        "coins": user["coins"],
        "cases_opened": user["cases_opened"],
        "inventory": json.loads(user["inventory"]),
    }


def save_state(user_id, state):
    with db_connection() as conn:
        conn.execute(
            "UPDATE users SET coins = ?, cases_opened = ?, inventory = ? WHERE id = ?",
            (state["coins"], state["cases_opened"], json.dumps(state["inventory"]), user_id),
        )


def public_state(state, user):
    return {"coins": state["coins"], "cases_opened": state["cases_opened"], "inventory": state["inventory"], "user": user_public(user)}


# ======================================================================
# API: АВТОРИЗАЦИЯ И ПРОФИЛЬ
# ======================================================================

@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(silent=True) or {}
    username, password = str(data.get("username", "")).strip(), str(data.get("password", ""))
    if not valid_username(username):
        return jsonify({"error": "invalid_username"}), 400
    if len(password) < 4 or len(password) > 128:
        return jsonify({"error": "invalid_password"}), 400
    # Для локальной демо-сборки роль закреплена за ником, который назвал пользователь.
    is_admin = int(username.casefold() == "lorren")
    try:
        with db_connection() as conn:
            cursor = conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)", (username, generate_password_hash(password), is_admin))
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({"error": "username_taken"}), 409
    session.clear()
    session["user_id"] = user_id
    user = get_user(user_id)
    return jsonify(public_state(get_state(user), user)), 201


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    username, password = str(data.get("username", "")).strip(), str(data.get("password", ""))
    with db_connection() as conn:
        user = conn.execute("SELECT id, username, password_hash, is_admin, is_banned, avatar_path, coins, cases_opened, inventory FROM users WHERE username = ?", (username,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "invalid_credentials"}), 401
    if user["is_banned"]:
        return jsonify({"error": "banned"}), 403
    session.clear()
    session["user_id"] = user["id"]
    return jsonify(public_state(get_state(user), user))


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/avatar", methods=["POST"])
@login_required
def api_avatar(user):
    file = request.files.get("avatar")
    if not file or not file.filename:
        return jsonify({"error": "avatar_missing"}), 400
    extension = secure_filename(file.filename).rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if (
        extension not in ALLOWED_AVATAR_EXTENSIONS
        or (file.mimetype and not file.mimetype.startswith("image/"))
        or not looks_like_image(file, extension)
    ):
        return jsonify({"error": "avatar_format"}), 400
    filename = f"{uuid.uuid4().hex}.{extension}"
    file.save(UPLOAD_DIR / filename)
    avatar_path = f"/static/uploads/{filename}"
    with db_connection() as conn:
        conn.execute("UPDATE users SET avatar_path = ? WHERE id = ?", (avatar_path, user["id"]))
    updated_user = get_user(user["id"])
    return jsonify(public_state(get_state(updated_user), updated_user))


# ======================================================================
# API: ИГРА
# ======================================================================

@app.route("/api/state")
@login_required
def api_state(user):
    return jsonify(public_state(get_state(user), user))


@app.route("/api/open_case/<case_id>", methods=["POST"])
@login_required
def api_open_case(user, case_id):
    state = get_state(user)
    case = next((case for case in CASES if case["id"] == case_id), None)
    if not case:
        return jsonify({"error": "not_found"}), 404
    if state["coins"] < case["price"]:
        return jsonify({"error": "insufficient_funds"}), 400
    state["coins"] -= case["price"]
    won = make_instance(weighted_random_item())
    state["inventory"].append(won)
    state["cases_opened"] += 1
    save_state(user["id"], state)
    return jsonify({**public_state(state, user), "won": won})


@app.route("/api/upgrade", methods=["POST"])
@login_required
def api_upgrade(user):
    state, data = get_state(user), request.get_json(silent=True) or {}
    instance_id = data.get("instance_id")
    try:
        chance = float(data.get("chance", 10))
    except (TypeError, ValueError):
        chance = 10.0
    chance = max(2.0, min(95.0, chance))
    input_item = next((item for item in state["inventory"] if item["instance_id"] == instance_id), None)
    if not input_item:
        return jsonify({"error": "item_not_found"}), 400
    if not has_upgrade_target(input_item):
        # Предмет уже самый дорогой в пуле — апгрейдить его дальше некуда.
        return jsonify({"error": "no_upgrade_available"}), 400
    success = random.uniform(0, 100) < chance
    state["inventory"] = [item for item in state["inventory"] if item["instance_id"] != instance_id]
    if success:
        target_value = round(input_item["value"] * (100.0 / chance))
        result_item = make_instance(find_upgrade_result(input_item, target_value))
        state["inventory"].append(result_item)
    else:
        result_item = input_item
    save_state(user["id"], state)
    return jsonify({**public_state(state, user), "success": success, "item": result_item})


@app.route("/api/buy", methods=["POST"])
@login_required
def api_buy(user):
    state, data = get_state(user), request.get_json(silent=True) or {}
    try:
        index = int(data.get("pack_index", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "bad_pack"}), 400
    if not 0 <= index < len(COIN_PACKS):
        return jsonify({"error": "bad_pack"}), 400
    pack = COIN_PACKS[index]
    state["coins"] += pack["coins"]
    save_state(user["id"], state)
    return jsonify({**public_state(state, user), "added": pack["coins"]})


# ======================================================================
# API: АДМИНИСТРАТОР
# ======================================================================

@app.route("/api/admin/users")
@admin_required
def api_admin_users(user):
    with db_connection() as conn:
        rows = conn.execute("SELECT id, username, is_admin, is_banned, coins, inventory FROM users ORDER BY username COLLATE NOCASE").fetchall()
    users = []
    for row in rows:
        coins = row["coins"] if row["coins"] is not None else 51240
        items = len(json.loads(row["inventory"])) if row["inventory"] is not None else len(START_ITEM_IDS)
        users.append({"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"]), "is_banned": bool(row["is_banned"]), "coins": coins, "items": items})
    return jsonify({"users": users})


@app.route("/api/admin/action", methods=["POST"])
@admin_required
def api_admin_action(admin):
    data, action = request.get_json(silent=True) or {}, None
    action = data.get("action")
    try:
        target_id = int(data.get("target_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "target_required"}), 400
    if target_id == admin["id"]:
        return jsonify({"error": "self_action_forbidden"}), 400
    target = get_user(target_id)
    if not target:
        return jsonify({"error": "user_not_found"}), 404
    if action == "coins":
        try:
            amount = int(data.get("amount"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid_amount"}), 400
        if not 1 <= amount <= 1_000_000:
            return jsonify({"error": "invalid_amount"}), 400
        target_state = get_state(target)
        target_state["coins"] += amount
        save_state(target_id, target_state)
        message = f"Начислено {amount} M"
    elif action == "character":
        item = item_by_id(data.get("item_id"))
        if not item:
            return jsonify({"error": "item_not_found"}), 400
        target_state = get_state(target)
        target_state["inventory"].append(make_instance(item))
        save_state(target_id, target_state)
        message = f"Выдан предмет «{item['name']}»"
    elif action == "ban":
        banned = bool(data.get("banned", True))
        with db_connection() as conn:
            conn.execute("UPDATE users SET is_banned = ? WHERE id = ?", (int(banned), target_id))
        message = "Пользователь заблокирован" if banned else "Пользователь разблокирован"
    else:
        return jsonify({"error": "unknown_action"}), 400
    return jsonify({"ok": True, "message": message})


# ======================================================================
# СТРАНИЦА
# ======================================================================

@app.route("/")
def index():
    return render_template("index.html", cases=CASES, rarity=RARITY, item_pool=ITEM_POOL, coin_packs=COIN_PACKS)


init_database()

if __name__ == "__main__":
    app.run(debug=True)
