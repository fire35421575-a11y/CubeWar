from flask import Flask, send_from_directory, request
from flask_socketio import SocketIO, emit, join_room
import os
import random
import string
import time
import math

app = Flask(__name__)
app.config['SECRET_KEY'] = 'cubewar_secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

SERVER_CODE = "MAIN"

GAME = {
    "players": {},
    "walls": {},
    "farms": {},
    "crates": {},
    "wall_id": 0,
    "farm_id": 0,
    "crate_id": 0,
    "last_crate_spawn": time.time(),
    "started": False,
    "start_time": 0,
    "zone": {"active": False, "left": 0, "top": 0, "right": 0, "bottom": 0, "warn": False},
    "last_zone_tick": 0,
    "passive_running": False,
    "next_idx": 0,
    "countdown_active": False,
    "countdown_started_at": 0,
}

COLORS = ["#e74c3c", "#3498db", "#2ecc71", "#9b59b6",
          "#f39c12", "#1abc9c", "#e91e63", "#34495e"]

MAX_PLAYERS = 6
COOLDOWN = 0.5
W, H = 1200, 1200
WALL_HP = 4
WALL_COST = 10
FARM_COST = 20
FARM_INCOME_TIME = 5
FARM_INCOME = 1
PASSIVE_INCOME_TIME = 5
PASSIVE_INCOME = 1
KILL_REWARD = 5
REGEN_TIME = 3
REGEN_AMOUNT = 2
START_COINS = 500
EMOTION_COOLDOWN = 6

CRATE_HP = 3
CRATE_RESPAWN = 15
MAX_CRATES = 4
BONUS_SHIELD_TIME = 10
BONUS_BIG_BULLETS_TIME = 10

BULLET_DMG = 5
BULLET_LIFE = 0.6

ZONE_START_TIME = 60
ZONE_TICK = 10
ZONE_DAMAGE = 2
ZONE_STEP = 40

COUNTDOWN_SECONDS = 20
MIN_PLAYERS = 2

GUN_LEVELS = [
    {"name": "Пистолет", "dmg": 5, "bullets": 1, "cost": 0,   "pierce": False},
    {"name": "Двойной",  "dmg": 5, "bullets": 2, "cost": 15,  "pierce": False},
    {"name": "Тройной",  "dmg": 5, "bullets": 3, "cost": 30,  "pierce": False},
    {"name": "Тяжёлый",  "dmg": 5, "bullets": 3, "cost": 60,  "pierce": False},
    {"name": "Лазер",    "dmg": 5, "bullets": 3, "cost": 120, "pierce": True},
]

BONUS_TYPES = ["shield", "big_bullets"]


def get_spawns(count):
    cx, cy = W // 2, H // 2
    r = min(W, H) // 2 - 150
    positions = []
    for i in range(count):
        angle = (2 * math.pi * i / count) - math.pi / 2
        x = int(cx + r * math.cos(angle))
        y = int(cy + r * math.sin(angle))
        x = round(x / 50) * 50
        y = round(y / 50) * 50
        x = max(80, min(W - 80, x))
        y = max(80, min(H - 80, y))
        positions.append((x, y))
    return positions


def random_crate_pos():
    for _ in range(50):
        x = random.randint(200, W - 200)
        y = random.randint(200, H - 200)
        x = round(x / 50) * 50
        y = round(y / 50) * 50
        if 150 < x < W - 150 and 150 < y < H - 150:
            return x, y
    return W // 2, H // 2


def check_wall_collision(game, x, y):
    half = 25
    for w in game["walls"].values():
        if w["hp"] <= 0:
            continue
        wx, wy = w["x"], w["y"]
        if (x + half > wx - 25 and x - half < wx + 25 and
                y + half > wy - 25 and y - half < wy + 25):
            return True
    return False


def check_farm_collision(game, x, y):
    for farm in game["farms"].values():
        if abs(farm["x"] - x) < 60 and abs(farm["y"] - y) < 60:
            return True
    return False


def check_crate_collision(game, x, y, exclude_id=None):
    for cid, crate in game["crates"].items():
        if crate["hp"] <= 0:
            continue
        if cid == exclude_id:
            continue
        if abs(crate["x"] - x) < 50 and abs(crate["y"] - y) < 50:
            return True
    return False


def in_zone(game, x, y):
    z = game.get("zone")
    if not z or not z.get("active"):
        return False
    left = z["left"]
    top = z["top"]
    right = W - z["right"]
    bottom = H - z["bottom"]
    return not (left <= x <= right and top <= y <= bottom)


def can_act(p):
    now = time.time()
    return (now - p.get("last_action", 0)) >= COOLDOWN


def mark_action(p):
    p["last_action"] = time.time()


def new_player_dict(name, idx):
    return {
        "name": name,
        "x": 0, "y": 0,
        "dir": {"x": 1, "y": 0},
        "hp": 100,
        "max_hp": 100,
        "coins": START_COINS,
        "kills": 0,
        "gun_level": 0,
        "color": COLORS[idx % len(COLORS)],
        "last_action": 0,
        "last_passive": time.time(),
        "last_regen": time.time(),
        "last_emotion": 0,
        "ready": False,
        "shield_until": 0,
        "big_bullets_until": 0,
        "last_zone_damage": 0,
    }


def reset_game():
    """Сброс стейта игры (не игроков)."""
    GAME["walls"] = {}
    GAME["farms"] = {}
    GAME["crates"] = {}
    GAME["wall_id"] = 0
    GAME["farm_id"] = 0
    GAME["crate_id"] = 0
    GAME["last_crate_spawn"] = time.time()
    GAME["started"] = False
    GAME["start_time"] = 0
    GAME["zone"] = {"active": False, "left": 0, "top": 0, "right": 0, "bottom": 0, "warn": False}
    GAME["last_zone_tick"] = 0
    GAME["countdown_active"] = False
    GAME["countdown_started_at"] = 0
    # сбрасываем игроков
    for p in GAME["players"].values():
        p["hp"] = 100
        p["coins"] = START_COINS
        p["kills"] = 0
        p["gun_level"] = 0
        p["shield_until"] = 0
        p["big_bullets_until"] = 0
        p["alive"] = True


def broadcast_player_list():
    players_info = {}
    for sid, p in GAME["players"].items():
        players_info[sid] = {
            "name": p["name"],
            "color": p["color"],
            "hp": p["hp"],
            "coins": p["coins"],
            "kills": p["kills"],
            "gun_level": p["gun_level"],
            "shield_until": p.get("shield_until", 0),
            "big_bullets_until": p.get("big_bullets_until", 0),
        }

    countdown_left = 0
    if GAME["countdown_active"]:
        elapsed = time.time() - GAME["countdown_started_at"]
        countdown_left = max(0, COUNTDOWN_SECONDS - int(elapsed))

    socketio.server.emit('server_update', {
        "players": players_info,
        "player_count": len(GAME["players"]),
        "max_players": MAX_PLAYERS,
        "countdown_active": GAME["countdown_active"],
        "countdown_left": countdown_left,
        "started": GAME["started"],
    }, room=SERVER_CODE, namespace='/')


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('.', path)


@socketio.on('join_server')
def on_join_server(data):
    sid = request.sid
    name = data.get('name', 'Игрок')[:12]

    if sid in GAME["players"]:
        emit('error_msg', {"text": "Ты уже на сервере"})
        return

    if GAME["started"]:
        alive = [s for s, p in GAME["players"].items() if p["hp"] > 0]
        if len(alive) == 0 and len(GAME["players"]) == 0:
            reset_game()
        else:
            emit('error_msg', {"text": "Игра уже идёт. Подожди следующую."})
            return

    if len(GAME["players"]) >= MAX_PLAYERS:
        emit('error_msg', {"text": "Сервер полон (6/6)"})
        return

    idx = GAME.get("next_idx", 0)
    GAME["next_idx"] = idx + 1
    GAME["players"][sid] = new_player_dict(name, idx)

    join_room(SERVER_CODE)

    emit('joined', {
        "my_color": GAME["players"][sid]["color"],
        "cooldown": COOLDOWN,
        "gun_levels": GUN_LEVELS,
        "farm_cost": FARM_COST,
        "wall_cost": WALL_COST,
        "world_w": W,
        "world_h": H,
    })

    broadcast_player_list()


def check_countdown():
    """Запуск таймера если нужно."""
    if GAME["started"]:
        return
    if GAME["countdown_active"]:
        return
    if len(GAME["players"]) < MIN_PLAYERS:
        return

    GAME["countdown_active"] = True
    GAME["countdown_started_at"] = time.time()

    if len(GAME["players"]) >= MAX_PLAYERS:
        GAME["countdown_started_at"] = time.time() - (COUNTDOWN_SECONDS - 5)

    broadcast_player_list()


def start_game():
    if GAME["started"]:
        return
    players = GAME["players"]
    if len(players) < MIN_PLAYERS:
        return

    GAME["started"] = True
    GAME["start_time"] = time.time()
    GAME["zone"] = {"active": False, "left": 0, "top": 0, "right": 0, "bottom": 0, "warn": False}
    GAME["last_zone_tick"] = 0

    spawns = get_spawns(len(players))
    for i, (sid, p) in enumerate(players.items()):
        p["x"], p["y"] = spawns[i]
        p["hp"] = 100
        p["coins"] = START_COINS
        p["kills"] = 0
        p["gun_level"] = 0
        p["last_passive"] = time.time()
        p["last_regen"] = time.time()
        p["last_emotion"] = 0
        p["shield_until"] = 0
        p["big_bullets_until"] = 0
        p["last_zone_damage"] = 0
        p["alive"] = True

    GAME["crates"] = {}
    GAME["crate_id"] = 0
    GAME["last_crate_spawn"] = time.time()

    players_info = {}
    for sid, p in players.items():
        players_info[sid] = {
            "name": p["name"],
            "x": p["x"], "y": p["y"],
            "dir": p["dir"],
            "hp": p["hp"],
            "max_hp": p["max_hp"],
            "coins": p["coins"],
            "kills": p["kills"],
            "gun_level": p["gun_level"],
            "color": p["color"],
            "shield_until": 0,
            "big_bullets_until": 0,
        }

    socketio.server.emit('game_started', {
        "players": players_info,
        "walls": GAME["walls"],
        "farms": GAME["farms"],
        "crates": GAME["crates"],
        "world_w": W,
        "world_h": H,
    }, room=SERVER_CODE, namespace='/')


def spawn_crate():
    x, y = random_crate_pos()
    for _ in range(20):
        if (not check_wall_collision(GAME, x, y) and
                not check_farm_collision(GAME, x, y) and
                not check_crate_collision(GAME, x, y)):
            break
        x, y = random_crate_pos()
    else:
        return None
    GAME["crate_id"] += 1
    cid = str(GAME["crate_id"])
    GAME["crates"][cid] = {
        "x": x, "y": y,
        "hp": CRATE_HP,
        "max_hp": CRATE_HP,
        "bonus": random.choice(BONUS_TYPES),
    }
    return cid, GAME["crates"][cid]


def passive_loop():
    """ЕДИНЫЙ цикл — таймер, игра, всё здесь."""
    tick_count = 0
    while True:
        socketio.sleep(1)
        tick_count += 1

        # === 1. Если нет игроков — спим и ждём ===
        if len(GAME["players"]) == 0:
            GAME["countdown_active"] = False
            GAME["started"] = False
            GAME["passive_running"] = False
            return

        # === 2. Фаза ожидания (таймер) ===
        if not GAME["started"]:
            if len(GAME["players"]) >= MIN_PLAYERS:
                if not GAME["countdown_active"]:
                    GAME["countdown_active"] = True
                    GAME["countdown_started_at"] = time.time()
                    # при 6 игроках — быстрый старт
                    if len(GAME["players"]) >= MAX_PLAYERS:
                        GAME["countdown_started_at"] = time.time() - (COUNTDOWN_SECONDS - 5)
                    broadcast_player_list()
                else:
                    # таймер идёт
                    elapsed = time.time() - GAME["countdown_started_at"]
                    left = COUNTDOWN_SECONDS - int(elapsed)
                    if left <= 0:
                        GAME["countdown_active"] = False
                        try:
                            start_game()
                        except Exception as e:
                            print("START_GAME ERROR:", e)
                    else:
                        broadcast_player_list()
            else:
                # игроков мало — сбрасываем таймер
                if GAME["countdown_active"]:
                    GAME["countdown_active"] = False
                    GAME["countdown_started_at"] = 0
                    broadcast_player_list()
            continue

        # === 3. Игра идёт ===
        now = time.time()
        elapsed = now - GAME.get("start_time", now)

        zone = GAME["zone"]
        if elapsed >= ZONE_START_TIME:
            if not zone["warn"]:
                zone["warn"] = True
                zone["active"] = True
                socketio.server.emit('zone_warning', {}, room=SERVER_CODE, namespace='/')
            if now - GAME.get("last_zone_tick", 0) >= ZONE_TICK:
                GAME["last_zone_tick"] = now
                zone["left"] += ZONE_STEP
                zone["top"] += ZONE_STEP
                zone["right"] += ZONE_STEP
                zone["bottom"] += ZONE_STEP
                if zone["left"] + zone["right"] >= W - 200:
                    zone["left"] = (W - 200) // 2
                    zone["right"] = (W - 200) // 2
                if zone["top"] + zone["bottom"] >= H - 200:
                    zone["top"] = (H - 200) // 2
                    zone["bottom"] = (H - 200) // 2
                socketio.server.emit('zone_update', {
                    "left": zone["left"],
                    "top": zone["top"],
                    "right": zone["right"],
                    "bottom": zone["bottom"],
                }, room=SERVER_CODE, namespace='/')

        for sid, p in GAME["players"].items():
            if p["hp"] <= 0:
                continue
            if now - p.get("last_passive", 0) >= PASSIVE_INCOME_TIME:
                p["coins"] += PASSIVE_INCOME
                p["last_passive"] = now

        for sid, p in GAME["players"].items():
            if p["hp"] <= 0:
                continue
            if now - p.get("last_regen", 0) >= REGEN_TIME:
                if p["hp"] < p["max_hp"]:
                    p["hp"] = min(p["max_hp"], p["hp"] + REGEN_AMOUNT)
                p["last_regen"] = now

        if zone["active"]:
            for sid, p in GAME["players"].items():
                if p["hp"] <= 0:
                    continue
                if in_zone(GAME, p["x"], p["y"]):
                    if now - p.get("last_zone_damage", 0) >= 1:
                        if now < p.get("shield_until", 0):
                            p["last_zone_damage"] = now
                            continue
                        p["hp"] = max(0, p["hp"] - ZONE_DAMAGE)
                        p["last_zone_damage"] = now
                        socketio.server.emit('player_hit', {
                            "sid": sid, "hp": p["hp"], "zone": True
                        }, room=SERVER_CODE, namespace='/')
                        if p["hp"] <= 0:
                            socketio.server.emit('player_died', {
                                "sid": sid, "killer": None, "zone": True
                            }, room=SERVER_CODE, namespace='/')
                            check_win()
            for wid, w in list(GAME["walls"].items()):
                if in_zone(GAME, w["x"], w["y"]):
                    w["hp"] -= 1
                    socketio.server.emit('wall_hit', {
                        "id": wid, "hp": w["hp"], "x": w["x"], "y": w["y"],
                    }, room=SERVER_CODE, namespace='/')
                    if w["hp"] <= 0:
                        del GAME["walls"][wid]
                        socketio.server.emit('wall_destroyed', {
                            "id": wid, "x": w["x"], "y": w["y"],
                        }, room=SERVER_CODE, namespace='/')
            for fid, f in list(GAME["farms"].items()):
                if in_zone(GAME, f["x"], f["y"]):
                    f["hp"] -= 1
                    socketio.server.emit('farm_hit', {
                        "id": fid, "hp": f["hp"], "x": f["x"], "y": f["y"],
                    }, room=SERVER_CODE, namespace='/')
                    if f["hp"] <= 0:
                        del GAME["farms"][fid]
                        socketio.server.emit('farm_destroyed', {
                            "id": fid, "x": f["x"], "y": f["y"],
                        }, room=SERVER_CODE, namespace='/')

        for fid, farm in list(GAME["farms"].items()):
            if farm["hp"] <= 0:
                del GAME["farms"][fid]
                continue
            if now - farm.get("last_income", 0) >= FARM_INCOME_TIME:
                owner_sid = farm.get("owner")
                if owner_sid and owner_sid in GAME["players"]:
                    GAME["players"][owner_sid]["coins"] += FARM_INCOME
                    socketio.server.emit('farm_income', {
                        "id": fid,
                        "x": farm["x"],
                        "y": farm["y"],
                        "amount": FARM_INCOME,
                        "owner": owner_sid,
                    }, room=SERVER_CODE, namespace='/')
                farm["last_income"] = now

        alive_crates = [c for c in GAME["crates"].values() if c["hp"] > 0]
        if (len(alive_crates) < MAX_CRATES and
                now - GAME.get("last_crate_spawn", 0) >= CRATE_RESPAWN):
            result = spawn_crate()
            if result:
                cid, crate = result
                socketio.server.emit('crate_spawned', {
                    "id": cid,
                    "x": crate["x"],
                    "y": crate["y"],
                    "hp": crate["hp"],
                    "max_hp": crate["max_hp"],
                    "bonus": crate["bonus"],
                }, room=SERVER_CODE, namespace='/')
                GAME["last_crate_spawn"] = now

        if tick_count % 2 == 0:
            socketio.server.emit('tick_update', {
                "players": {
                    s: {
                        "coins": p["coins"],
                        "hp": p["hp"],
                        "kills": p["kills"],
                        "shield_until": p.get("shield_until", 0),
                        "big_bullets_until": p.get("big_bullets_until", 0),
                    }
                    for s, p in GAME["players"].items()
                },
                "crates": {
                    cid: {"hp": c["hp"], "x": c["x"], "y": c["y"], "bonus": c["bonus"]}
                    for cid, c in GAME["crates"].items() if c["hp"] > 0
                },
                "zone": {
                    "active": zone["active"],
                    "left": zone["left"],
                    "top": zone["top"],
                    "right": zone["right"],
                    "bottom": zone["bottom"],
                    "warn": zone["warn"],
                },
                "elapsed": elapsed,
            }, room=SERVER_CODE, namespace='/')


def start_passive_if_needed():
    if not GAME.get("passive_running"):
        GAME["passive_running"] = True
        socketio.start_background_task(passive_loop)


def check_win():
    alive = [s for s, p in GAME["players"].items() if p["hp"] > 0]
    if len(alive) <= 1 and len(GAME["players"]) > 1:
        winner = GAME["players"].get(alive[0]) if alive else None
        socketio.server.emit('game_over', {
            "winner": winner["name"] if winner else "Ничья",
            "sid": alive[0] if alive else None,
        }, room=SERVER_CODE, namespace='/')
        socketio.start_background_task(reset_after_game)


def reset_after_game():
    socketio.sleep(5)
    reset_game()
    socketio.server.emit('server_reset', {}, room=SERVER_CODE, namespace='/')


@socketio.on('emotion')
def on_emotion(data):
    sid = request.sid
    if sid not in GAME["players"]:
        return
    p = GAME["players"][sid]
    if p["hp"] <= 0 or not GAME.get("started"):
        return
    now = time.time()
    last = p.get("last_emotion", 0)
    if now - last < EMOTION_COOLDOWN:
        left = EMOTION_COOLDOWN - (now - last)
        emit('emotion_cooldown', {"left": left}, to=sid)
        return
    p["last_emotion"] = now
    emoji = data.get("emoji", "😂")
    if len(emoji) > 4:
        emoji = emoji[:4]
    emit('emotion_shown', {
        "sid": sid,
        "emoji": emoji,
        "x": p["x"],
        "y": p["y"],
    }, to=SERVER_CODE)


@socketio.on('move')
def on_move(data):
    sid = request.sid
    if sid not in GAME["players"]:
        return
    p = GAME["players"][sid]
    if p["hp"] <= 0 or not GAME.get("started"):
        return
    if not can_act(p):
        emit('on_cooldown', {}, to=sid)
        return
    nx = data.get("x", p["x"])
    ny = data.get("y", p["y"])
    if check_wall_collision(GAME, nx, ny):
        emit('error_msg', {"text": "Стена!"})
        return
    if check_farm_collision(GAME, nx, ny):
        emit('error_msg', {"text": "Ферма!"})
        return
    if check_crate_collision(GAME, nx, ny):
        emit('error_msg', {"text": "Ящик!"})
        return
    p["x"] = nx
    p["y"] = ny
    p["dir"] = data.get("dir", p["dir"])
    mark_action(p)
    emit('player_moved', {
        "sid": sid, "x": p["x"], "y": p["y"], "dir": p["dir"],
    }, to=SERVER_CODE)


@socketio.on('place_wall')
def on_place_wall(data):
    sid = request.sid
    if sid not in GAME["players"]:
        return
    p = GAME["players"][sid]
    if p["hp"] <= 0 or not GAME.get("started"):
        return
    if not can_act(p):
        emit('on_cooldown', {}, to=sid)
        return
    if p["coins"] < WALL_COST:
        emit('error_msg', {"text": f"Нужно {WALL_COST} очков"})
        return
    wx = p["x"] - p["dir"]["x"] * 50
    wy = p["y"] - p["dir"]["y"] * 50
    wx = max(25, min(W - 25, wx))
    wy = max(25, min(H - 25, wy))
    for other_sid, other in GAME["players"].items():
        if other_sid == sid:
            continue
        if other["hp"] <= 0:
            continue
        if abs(other["x"] - wx) < 50 and abs(other["y"] - wy) < 50:
            emit('error_msg', {"text": "Тут игрок"})
            return
    if check_wall_collision(GAME, wx, wy):
        return
    if check_farm_collision(GAME, wx, wy):
        return
    if check_crate_collision(GAME, wx, wy):
        emit('error_msg', {"text": "Тут ящик"})
        return
    GAME["wall_id"] += 1
    wid = str(GAME["wall_id"])
    GAME["walls"][wid] = {"x": wx, "y": wy, "hp": WALL_HP, "owner": sid}
    p["coins"] -= WALL_COST
    mark_action(p)
    emit('wall_placed', {
        "id": wid, "x": wx, "y": wy, "hp": WALL_HP,
        "my_coins": p["coins"],
    }, to=SERVER_CODE)


@socketio.on('place_farm')
def on_place_farm(data):
    sid = request.sid
    if sid not in GAME["players"]:
        return
    p = GAME["players"][sid]
    if p["hp"] <= 0 or not GAME.get("started"):
        return
    if p["coins"] < FARM_COST:
        emit('error_msg', {"text": f"Нужно {FARM_COST} очков"})
        return
    wx = p["x"] - p["dir"]["x"] * 50
    wy = p["y"] - p["dir"]["y"] * 50
    wx = max(40, min(W - 40, wx))
    wy = max(40, min(H - 40, wy))
    for other_sid, other in GAME["players"].items():
        if other_sid == sid:
            continue
        if other["hp"] <= 0:
            continue
        if abs(other["x"] - wx) < 60 and abs(other["y"] - wy) < 60:
            emit('error_msg', {"text": "Тут игрок"})
            return
    if check_wall_collision(GAME, wx, wy):
        emit('error_msg', {"text": "Стена мешает"})
        return
    if check_farm_collision(GAME, wx, wy):
        emit('error_msg', {"text": "Тут уже ферма"})
        return
    if check_crate_collision(GAME, wx, wy):
        emit('error_msg', {"text": "Тут ящик"})
        return
    GAME["farm_id"] += 1
    fid = str(GAME["farm_id"])
    GAME["farms"][fid] = {
        "x": wx, "y": wy,
        "hp": WALL_HP * 2,
        "owner": sid,
        "last_income": time.time(),
    }
    p["coins"] -= FARM_COST
    emit('farm_placed', {
        "id": fid, "x": wx, "y": wy, "hp": WALL_HP * 2,
        "my_coins": p["coins"],
    }, to=SERVER_CODE)


@socketio.on('upgrade_gun')
def on_upgrade_gun(data):
    sid = request.sid
    if sid not in GAME["players"]:
        return
    p = GAME["players"][sid]
    if p["hp"] <= 0 or not GAME.get("started"):
        return
    cur = p["gun_level"]
    nxt = cur + 1
    if nxt >= len(GUN_LEVELS):
        emit('error_msg', {"text": "Максимум"})
        return
    cost = GUN_LEVELS[nxt]["cost"]
    if p["coins"] < cost:
        emit('error_msg', {"text": f"Нужно {cost} очков"})
        return
    p["coins"] -= cost
    p["gun_level"] = nxt
    emit('gun_upgraded', {
        "sid": sid,
        "gun_level": nxt,
        "my_coins": p["coins"],
    }, to=SERVER_CODE)


@socketio.on('shoot')
def on_shoot(data):
    sid = request.sid
    if sid not in GAME["players"]:
        return
    p = GAME["players"][sid]
    if p["hp"] <= 0 or not GAME.get("started"):
        return
    if not can_act(p):
        emit('on_cooldown', {}, to=sid)
        return
    lvl = p["gun_level"]
    gun = GUN_LEVELS[lvl]
    now = time.time()
    big = now < p.get("big_bullets_until", 0)
    mark_action(p)
    emit('bullet_fired', {
        "sid": sid,
        "x": p["x"], "y": p["y"],
        "dir": p["dir"],
        "color": p["color"],
        "dmg": BULLET_DMG,
        "bullets": gun["bullets"],
        "pierce": gun["pierce"],
        "gun_level": lvl,
        "big": big,
    }, to=SERVER_CODE)


@socketio.on('hit')
def on_hit(data):
    target_sid = data.get("target_sid")
    dmg = data.get("dmg", BULLET_DMG)
    if target_sid not in GAME["players"]:
        return
    p = GAME["players"][target_sid]
    if p["hp"] <= 0:
        return
    if time.time() < p.get("shield_until", 0):
        emit('player_shielded', {"sid": target_sid}, to=SERVER_CODE)
        return
    p["hp"] = max(0, p["hp"] - dmg)
    emit('player_hit', {"sid": target_sid, "hp": p["hp"]}, to=SERVER_CODE)
    if p["hp"] <= 0:
        killer_sid = data.get("killer")
        if killer_sid and killer_sid in GAME["players"]:
            GAME["players"][killer_sid]["coins"] += KILL_REWARD
            GAME["players"][killer_sid]["kills"] += 1
        emit('player_died', {
            "sid": target_sid,
            "killer": killer_sid,
        }, to=SERVER_CODE)
        check_win()


@socketio.on('hit_wall')
def on_hit_wall(data):
    wid = data.get("wall_id")
    if wid in GAME["walls"]:
        w = GAME["walls"][wid]
        w["hp"] -= 1
        emit('wall_hit', {
            "id": wid, "hp": w["hp"], "x": w["x"], "y": w["y"],
        }, to=SERVER_CODE)
        if w["hp"] <= 0:
            del GAME["walls"][wid]
            emit('wall_destroyed', {
                "id": wid, "x": w["x"], "y": w["y"],
            }, to=SERVER_CODE)


@socketio.on('hit_farm')
def on_hit_farm(data):
    fid = data.get("farm_id")
    if fid in GAME["farms"]:
        f = GAME["farms"][fid]
        f["hp"] -= 1
        emit('farm_hit', {
            "id": fid, "hp": f["hp"], "x": f["x"], "y": f["y"],
        }, to=SERVER_CODE)
        if f["hp"] <= 0:
            del GAME["farms"][fid]
            emit('farm_destroyed', {
                "id": fid, "x": f["x"], "y": f["y"],
            }, to=SERVER_CODE)


@socketio.on('hit_crate')
def on_hit_crate(data):
    cid = data.get("crate_id")
    sid = request.sid
    if cid not in GAME["crates"]:
        return
    c = GAME["crates"][cid]
    if c["hp"] <= 0:
        return
    c["hp"] -= 1
    emit('crate_hit', {
        "id": cid, "hp": c["hp"], "x": c["x"], "y": c["y"],
    }, to=SERVER_CODE)
    if c["hp"] <= 0:
        bonus = c["bonus"]
        if sid in GAME["players"]:
            p = GAME["players"][sid]
            now = time.time()
            if bonus == "shield":
                p["shield_until"] = now + BONUS_SHIELD_TIME
            elif bonus == "big_bullets":
                p["big_bullets_until"] = now + BONUS_BIG_BULLETS_TIME
        emit('crate_destroyed', {
            "id": cid, "x": c["x"], "y": c["y"],
            "bonus": bonus,
            "player_sid": sid,
        }, to=SERVER_CODE)
        del GAME["crates"][cid]


@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    if sid in GAME["players"]:
        del GAME["players"][sid]
        emit('player_left', {"sid": sid}, to=SERVER_CODE)
        broadcast_player_list()
        if len(GAME["players"]) < MIN_PLAYERS:
            GAME["countdown_active"] = False
            GAME["countdown_started_at"] = 0
            broadcast_player_list()
        if len(GAME["players"]) == 0:
            reset_game()
            GAME["passive_running"] = False
            socketio.server.emit('server_reset', {}, room=SERVER_CODE, namespace='/')


# === ЗАПУСК ЕДИНОГО ЦИКЛА ПРИ СТАРТЕ СЕРВЕРА ===
def start_passive_on_boot():
    """Запускаем единый цикл сразу при старте сервера."""
    socketio.start_background_task(passive_loop)


# Запускаем через 1 секунду после старта
import threading
def delayed_start():
    time.sleep(2)
    start_passive_if_needed()

threading.Thread(target=delayed_start, daemon=True).start()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
