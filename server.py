from flask import Flask, send_from_directory, request
from flask_socketio import SocketIO, emit, join_room
import os
import random
import string
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'cubewar_secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

GAMES = {}

COLORS = ["#e74c3c", "#3498db", "#2ecc71", "#9b59b6",
          "#f39c12", "#1abc9c", "#e91e63", "#34495e"]

MAX_PLAYERS = 4
COOLDOWN = 0.5
W, H = 800, 800
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

GUN_LEVELS = [
    {"name": "Пистолет", "dmg": 15, "bullets": 1, "cost": 0,   "pierce": False},
    {"name": "Двойной",  "dmg": 15, "bullets": 2, "cost": 15,  "pierce": False},
    {"name": "Тройной",  "dmg": 15, "bullets": 3, "cost": 30,  "pierce": False},
    {"name": "Тяжёлый",  "dmg": 25, "bullets": 3, "cost": 60,  "pierce": False},
    {"name": "Лазер",    "dmg": 20, "bullets": 3, "cost": 120, "pierce": True},
]


def generate_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def get_spawns(count):
    all_positions = [
        (80, 80), (W - 80, 80), (80, H - 80), (W - 80, H - 80),
        (W // 2, 80), (W // 2, H - 80), (80, H // 2), (W - 80, H // 2),
        (W // 3, H // 3), (W * 2 // 3, H // 3),
        (W // 3, H * 2 // 3), (W * 2 // 3, H * 2 // 3),
    ]
    random.shuffle(all_positions)
    return all_positions[:count]


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


def can_act(p):
    now = time.time()
    return (now - p.get("last_action", 0)) >= COOLDOWN


def mark_action(p):
    p["last_action"] = time.time()


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('.', path)


@socketio.on('create_game')
def on_create(data):
    code = generate_code()
    while code in GAMES:
        code = generate_code()
    sid = request.sid
    name = data.get('name', 'Игрок')[:12]
    GAMES[code] = {
        "host": sid,
        "players": {},
        "walls": {},
        "farms": {},
        "wall_id": 0,
        "farm_id": 0,
        "started": False,
    }
    # ВАЖНО: добавляем хоста в players
    GAMES[code]["players"][sid] = {
        "name": name,
        "x": 0, "y": 0,
        "dir": {"x": 1, "y": 0},
        "hp": 100,
        "max_hp": 100,
        "coins": START_COINS,
        "kills": 0,
        "gun_level": 0,
        "color": COLORS[0],
        "last_action": 0,
        "last_passive": time.time(),
        "last_regen": time.time(),
        "last_emotion": 0,
        "ready": False,
    }
    join_room(code)
    emit('joined', {
        "code": code,
        "players": GAMES[code]["players"],
        "my_color": COLORS[0],
        "cooldown": COOLDOWN,
        "walls": {},
        "farms": {},
        "gun_levels": GUN_LEVELS,
        "farm_cost": FARM_COST,
        "wall_cost": WALL_COST,
        "started": False,
    })

@socketio.on('join_game')
def on_join(data):
    code = data.get('code', '').upper()
    sid = request.sid
    name = data.get('name', 'Игрок')[:12]
    if code not in GAMES:
        emit('error_msg', {"text": "Комната не найдена"})
        return
    game = GAMES[code]
    if len(game["players"]) >= MAX_PLAYERS:
        emit('error_msg', {"text": "Комната полна"})
        return
    if game.get("started"):
        emit('error_msg', {"text": "Игра уже началась"})
        return
    idx = len(game["players"])
    game["players"][sid] = {
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
    }
    join_room(code)
    emit('joined', {
        "code": code,
        "players": game["players"],
        "my_color": COLORS[idx % len(COLORS)],
        "cooldown": COOLDOWN,
        "walls": game["walls"],
        "farms": game["farms"],
        "gun_levels": GUN_LEVELS,
        "farm_cost": FARM_COST,
        "wall_cost": WALL_COST,
        "started": False,
    })
    emit('player_joined', {
        "sid": sid,
        "player": game["players"][sid],
    }, to=code, include_self=False)


@socketio.on('toggle_ready')
def on_toggle_ready(data):
    sid = request.sid
    for code, game in GAMES.items():
        if sid in game["players"]:
            p = game["players"][sid]
            p["ready"] = not p.get("ready", False)
            emit('ready_changed', {
                "sid": sid,
                "ready": p["ready"],
            }, to=code)
            break


@socketio.on('start_game')
def on_start_game(data):
    code = data.get('code', '').upper()
    if code not in GAMES:
        return
    game = GAMES[code]
    if request.sid != game["host"]:
        emit('error_msg', {"text": "Только хост"})
        return
    if game.get("started"):
        return
    players = game["players"]
    if len(players) < 1:
        emit('error_msg', {"text": "Нужен хотя бы 1 игрок"})
        return
    if len(players) > 1:
        not_ready = [p["name"] for p in players.values() if not p.get("ready")]
        if not_ready:
            emit('error_msg', {"text": "Не все готовы: " + ", ".join(not_ready)})
            return

    game["started"] = True
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

    emit('game_started', {
        "players": players,
        "walls": game["walls"],
        "farms": game["farms"],
    }, to=code)

    socketio.start_background_task(passive_loop, code)


def passive_loop(code):
    """Каждую секунду: доход, реген, фермы. Только socketio.server.emit!"""
    while True:
        socketio.sleep(1)
        if code not in GAMES:
            return
        g = GAMES[code]
        if not g.get("started"):
            return
        now = time.time()

        # Пассивный доход
        for sid, p in g["players"].items():
            if p["hp"] <= 0:
                continue
            if now - p.get("last_passive", 0) >= PASSIVE_INCOME_TIME:
                p["coins"] += PASSIVE_INCOME
                p["last_passive"] = now

        # Регенерация
        for sid, p in g["players"].items():
            if p["hp"] <= 0:
                continue
            if now - p.get("last_regen", 0) >= REGEN_TIME:
                if p["hp"] < p["max_hp"]:
                    p["hp"] = min(p["max_hp"], p["hp"] + REGEN_AMOUNT)
                p["last_regen"] = now

        # Доход с ферм
        for fid, farm in list(g["farms"].items()):
            if farm["hp"] <= 0:
                del g["farms"][fid]
                continue
            if now - farm.get("last_income", 0) >= FARM_INCOME_TIME:
                owner_sid = farm.get("owner")
                if owner_sid and owner_sid in g["players"]:
                    g["players"][owner_sid]["coins"] += FARM_INCOME
                    print(f"[FARM INCOME] farm {fid} -> {g['players'][owner_sid]['name']} +{FARM_INCOME}")
                    socketio.server.emit('farm_income', {
                        "id": fid,
                        "x": farm["x"],
                        "y": farm["y"],
                        "amount": FARM_INCOME,
                        "owner": owner_sid,
                    }, room=code, namespace='/')
                farm["last_income"] = now

        # ВАЖНО: socketio.server.emit, не socketio.emit
        socketio.server.emit('tick_update', {
            "players": {
                s: {"coins": p["coins"], "hp": p["hp"], "kills": p["kills"]}
                for s, p in g["players"].items()
            }
        }, room=code, namespace='/')


@socketio.on('emotion')
def on_emotion(data):
    sid = request.sid
    for code, game in GAMES.items():
        if sid in game["players"]:
            p = game["players"][sid]
            if p["hp"] <= 0 or not game.get("started"):
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
            }, to=code)
            break


@socketio.on('move')
def on_move(data):
    sid = request.sid
    for code, game in GAMES.items():
        if sid in game["players"]:
            p = game["players"][sid]
            if p["hp"] <= 0 or not game.get("started"):
                return
            if not can_act(p):
                emit('on_cooldown', {}, to=sid)
                return
            nx = data.get("x", p["x"])
            ny = data.get("y", p["y"])
            if check_wall_collision(game, nx, ny):
                emit('error_msg', {"text": "Стена!"})
                return
            if check_farm_collision(game, nx, ny):
                emit('error_msg', {"text": "Ферма!"})
                return
            p["x"] = nx
            p["y"] = ny
            p["dir"] = data.get("dir", p["dir"])
            mark_action(p)
            emit('player_moved', {
                "sid": sid, "x": p["x"], "y": p["y"], "dir": p["dir"],
            }, to=code)
            break


@socketio.on('place_wall')
def on_place_wall(data):
    sid = request.sid
    for code, game in GAMES.items():
        if sid in game["players"]:
            p = game["players"][sid]
            if p["hp"] <= 0 or not game.get("started"):
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
            for other_sid, other in game["players"].items():
                if other_sid == sid:
                    continue
                if other["hp"] <= 0:
                    continue
                if abs(other["x"] - wx) < 50 and abs(other["y"] - wy) < 50:
                    emit('error_msg', {"text": "Тут игрок"})
                    return
            if check_wall_collision(game, wx, wy):
                return
            if check_farm_collision(game, wx, wy):
                return
            game["wall_id"] += 1
            wid = str(game["wall_id"])
            game["walls"][wid] = {"x": wx, "y": wy, "hp": WALL_HP, "owner": sid}
            p["coins"] -= WALL_COST
            mark_action(p)
            emit('wall_placed', {
                "id": wid, "x": wx, "y": wy, "hp": WALL_HP,
                "my_coins": p["coins"],
            }, to=code)
            break


@socketio.on('place_farm')
def on_place_farm(data):
    sid = request.sid
    for code, game in GAMES.items():
        if sid in game["players"]:
            p = game["players"][sid]
            if p["hp"] <= 0 or not game.get("started"):
                return
            if p["coins"] < FARM_COST:
                emit('error_msg', {"text": f"Нужно {FARM_COST} очков"})
                return
            wx = p["x"] - p["dir"]["x"] * 50
            wy = p["y"] - p["dir"]["y"] * 50
            wx = max(40, min(W - 40, wx))
            wy = max(40, min(H - 40, wy))
            for other_sid, other in game["players"].items():
                if other_sid == sid:
                    continue
                if other["hp"] <= 0:
                    continue
                if abs(other["x"] - wx) < 60 and abs(other["y"] - wy) < 60:
                    emit('error_msg', {"text": "Тут игрок"})
                    return
            if check_wall_collision(game, wx, wy):
                emit('error_msg', {"text": "Стена мешает"})
                return
            if check_farm_collision(game, wx, wy):
                emit('error_msg', {"text": "Тут уже ферма"})
                return
            game["farm_id"] += 1
            fid = str(game["farm_id"])
            game["farms"][fid] = {
                "x": wx, "y": wy,
                "hp": WALL_HP * 2,
                "owner": sid,
                "last_income": time.time(),
            }
            p["coins"] -= FARM_COST
            print(f"[FARM PLACED] {p['name']} farm {fid} at {wx},{wy}")
            emit('farm_placed', {
                "id": fid, "x": wx, "y": wy, "hp": WALL_HP * 2,
                "my_coins": p["coins"],
            }, to=code)
            break


@socketio.on('upgrade_gun')
def on_upgrade_gun(data):
    sid = request.sid
    for code, game in GAMES.items():
        if sid in game["players"]:
            p = game["players"][sid]
            if p["hp"] <= 0 or not game.get("started"):
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
            }, to=code)
            break


@socketio.on('shoot')
def on_shoot(data):
    sid = request.sid
    for code, game in GAMES.items():
        if sid in game["players"]:
            p = game["players"][sid]
            if p["hp"] <= 0 or not game.get("started"):
                return
            if not can_act(p):
                emit('on_cooldown', {}, to=sid)
                return
            lvl = p["gun_level"]
            gun = GUN_LEVELS[lvl]
            mark_action(p)
            emit('bullet_fired', {
                "sid": sid,
                "x": p["x"], "y": p["y"],
                "dir": p["dir"],
                "color": p["color"],
                "dmg": gun["dmg"],
                "bullets": gun["bullets"],
                "pierce": gun["pierce"],
                "gun_level": lvl,
            }, to=code)
            break


@socketio.on('hit')
def on_hit(data):
    target_sid = data.get("target_sid")
    dmg = data.get("dmg", 15)
    for code, game in GAMES.items():
        if target_sid in game["players"]:
            p = game["players"][target_sid]
            if p["hp"] <= 0:
                break
            p["hp"] = max(0, p["hp"] - dmg)
            emit('player_hit', {"sid": target_sid, "hp": p["hp"]}, to=code)
            if p["hp"] <= 0:
                killer_sid = data.get("killer")
                if killer_sid and killer_sid in game["players"]:
                    game["players"][killer_sid]["coins"] += KILL_REWARD
                    game["players"][killer_sid]["kills"] += 1
                emit('player_died', {
                    "sid": target_sid,
                    "killer": killer_sid,
                }, to=code)
                alive = [s for s, pl in game["players"].items() if pl["hp"] > 0]
                if len(alive) <= 1 and len(game["players"]) > 1:
                    winner = game["players"].get(alive[0]) if alive else None
                    emit('game_over', {
                        "winner": winner["name"] if winner else "Ничья",
                        "sid": alive[0] if alive else None,
                    }, to=code)
            break


@socketio.on('hit_wall')
def on_hit_wall(data):
    wid = data.get("wall_id")
    for code, game in GAMES.items():
        if wid in game["walls"]:
            w = game["walls"][wid]
            w["hp"] -= 1
            emit('wall_hit', {
                "id": wid, "hp": w["hp"], "x": w["x"], "y": w["y"],
            }, to=code)
            if w["hp"] <= 0:
                del game["walls"][wid]
                emit('wall_destroyed', {
                    "id": wid, "x": w["x"], "y": w["y"],
                }, to=code)
            break


@socketio.on('hit_farm')
def on_hit_farm(data):
    fid = data.get("farm_id")
    for code, game in GAMES.items():
        if fid in game["farms"]:
            f = game["farms"][fid]
            f["hp"] -= 1
            emit('farm_hit', {
                "id": fid, "hp": f["hp"], "x": f["x"], "y": f["y"],
            }, to=code)
            if f["hp"] <= 0:
                del game["farms"][fid]
                emit('farm_destroyed', {
                    "id": fid, "x": f["x"], "y": f["y"],
                }, to=code)
            break


@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    for code, game in list(GAMES.items()):
        if sid in game["players"]:
            del game["players"][sid]
            emit('player_left', {"sid": sid}, to=code)
            if not game["players"]:
                del GAMES[code]
            elif sid == game.get("host") and game["players"]:
                game["host"] = list(game["players"].keys())[0]
            break


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
