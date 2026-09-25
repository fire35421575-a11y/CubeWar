from flask import Flask, send_from_directory, request
from flask_socketio import SocketIO, emit, join_room
import os
import random
import string

app = Flask(__name__)
app.config['SECRET_KEY'] = 'cubewar_secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

GAMES = {}

COLORS = ["#e74c3c", "#3498db", "#2ecc71", "#9b59b6"]

MAX_PLAYERS = 4
ACTIONS_PER_ROUND = 10
ROUND_TIME = 50
PAUSE_TIME = 3
W, H = 800, 800
WALL_HP = 4


def generate_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def get_spawn(idx):
    positions = [(80, 80), (W - 80, 80), (80, H - 80), (W - 80, H - 80)]
    return positions[idx % len(positions)]


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
    px, py = get_spawn(0)
    GAMES[code] = {
        "host": sid,
        "players": {
            sid: {
                "name": name,
                "x": px, "y": py,
                "dir": {"x": 1, "y": 0},
                "hp": 100,
                "actions_left": ACTIONS_PER_ROUND,
                "color": COLORS[0],
            }
        },
        "walls": {},
        "wall_id": 0,
        "round_active": False,
        "round_num": 0,
    }
    join_room(code)
    emit('joined', {
        "code": code,
        "players": GAMES[code]["players"],
        "my_color": COLORS[0],
        "actions_per_round": ACTIONS_PER_ROUND,
        "round_time": ROUND_TIME,
        "walls": {},
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
    idx = len(game["players"])
    px, py = get_spawn(idx)
    game["players"][sid] = {
        "name": name,
        "x": px, "y": py,
        "dir": {"x": 1, "y": 0},
        "hp": 100,
        "actions_left": ACTIONS_PER_ROUND,
        "color": COLORS[idx % len(COLORS)],
    }
    join_room(code)
    emit('joined', {
        "code": code,
        "players": game["players"],
        "my_color": COLORS[idx % len(COLORS)],
        "actions_per_round": ACTIONS_PER_ROUND,
        "round_time": ROUND_TIME,
        "walls": game["walls"],
    })
    emit('player_joined', {
        "sid": sid,
        "player": game["players"][sid],
    }, to=code, include_self=False)


@socketio.on('start_round')
def on_start_round(data):
    code = data.get('code', '').upper()
    if code not in GAMES:
        return
    game = GAMES[code]
    if request.sid != game["host"]:
        return
    if game.get("round_active"):
        return
    game["round_active"] = True
    game["round_num"] = game.get("round_num", 0) + 1
    for p in game["players"].values():
        p["actions_left"] = ACTIONS_PER_ROUND
    emit('round_started', {
        "round_time": ROUND_TIME,
        "actions_per_round": ACTIONS_PER_ROUND,
        "round_num": game["round_num"],
    }, to=code)
    socketio.start_background_task(round_loop, code)


def round_loop(code):
    """Цикл раундов: игра → пауза → игра."""
    while True:
        # ИГРА
        for _ in range(ROUND_TIME):
            socketio.sleep(1)
            if code not in GAMES:
                return
            if not GAMES[code].get("round_active"):
                return
        if code not in GAMES:
            return

        # КОНЕЦ РАУНДА
        g = GAMES[code]
        g["round_active"] = False
        emit('round_ended', {"pause": PAUSE_TIME}, to=code)

        # ПАУЗА
        for _ in range(PAUSE_TIME):
            socketio.sleep(1)
            if code not in GAMES:
                return
        if code not in GAMES:
            return

        # ПРОВЕРКА НА ПОБЕДУ
        g = GAMES[code]
        alive = [p for p in g["players"].values() if p["hp"] > 0]
        if len(alive) <= 1:
            emit('game_over', {}, to=code)
            return

        # НОВЫЙ РАУНД
        g["round_active"] = True
        g["round_num"] = g.get("round_num", 0) + 1
        for p in g["players"].values():
            if p["hp"] > 0:
                p["actions_left"] = ACTIONS_PER_ROUND

        emit('round_started', {
            "round_time": ROUND_TIME,
            "actions_per_round": ACTIONS_PER_ROUND,
            "round_num": g["round_num"],
        }, to=code)


@socketio.on('move')
def on_move(data):
    sid = request.sid
    for code, game in GAMES.items():
        if sid in game["players"]:
            p = game["players"][sid]
            if p["hp"] <= 0:
                return
            if not game.get("round_active"):
                return
            if p["actions_left"] <= 0:
                emit('no_actions', {}, to=sid)
                return
            nx = data.get("x", p["x"])
            ny = data.get("y", p["y"])
            if check_wall_collision(game, nx, ny):
                emit('error_msg', {"text": "Стена!"})
                return
            p["x"] = nx
            p["y"] = ny
            p["dir"] = data.get("dir", p["dir"])
            p["actions_left"] -= 1
            emit('player_moved', {
                "sid": sid, "x": p["x"], "y": p["y"],
                "dir": p["dir"], "actions_left": p["actions_left"],
            }, to=code)
            break


@socketio.on('place_wall')
def on_place_wall(data):
    sid = request.sid
    for code, game in GAMES.items():
        if sid in game["players"]:
            p = game["players"][sid]
            if p["hp"] <= 0 or not game.get("round_active"):
                return
            if p["actions_left"] <= 0:
                emit('no_actions', {}, to=sid)
                return
            wx = p["x"] - p["dir"]["x"] * 50
            wy = p["y"] - p["dir"]["y"] * 50
            wx = max(25, min(W - 25, wx))
            wy = max(25, min(H - 25, wy))
            for other in game["players"].values():
                if other["hp"] <= 0:
                    continue
                if abs(other["x"] - wx) < 50 and abs(other["y"] - wy) < 50:
                    return
            if check_wall_collision(game, wx, wy):
                return
            game["wall_id"] = game.get("wall_id", 0) + 1
            wid = str(game["wall_id"])
            game["walls"][wid] = {
                "x": wx, "y": wy,
                "hp": WALL_HP,
                "owner": sid,
            }
            p["actions_left"] -= 1
            emit('wall_placed', {
                "id": wid, "x": wx, "y": wy, "hp": WALL_HP,
                "actions_left": p["actions_left"],
            }, to=code)
            break


@socketio.on('shoot')
def on_shoot(data):
    sid = request.sid
    for code, game in GAMES.items():
        if sid in game["players"]:
            p = game["players"][sid]
            if p["hp"] <= 0 or not game.get("round_active"):
                return
            if p["actions_left"] <= 0:
                emit('no_actions', {}, to=sid)
                return
            p["actions_left"] -= 1
            emit('bullet_fired', {
                "sid": sid,
                "x": p["x"], "y": p["y"],
                "dir": p["dir"],
                "color": p["color"],
                "actions_left": p["actions_left"],
            }, to=code)
            break


@socketio.on('hit')
def on_hit(data):
    target_sid = data.get("target_sid")
    dmg = data.get("dmg", 20)
    for code, game in GAMES.items():
        if target_sid in game["players"]:
            p = game["players"][target_sid]
            if p["hp"] <= 0:
                break
            p["hp"] = max(0, p["hp"] - dmg)
            emit('player_hit', {"sid": target_sid, "hp": p["hp"]}, to=code)
            if p["hp"] <= 0:
                emit('player_died', {"sid": target_sid}, to=code)
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
