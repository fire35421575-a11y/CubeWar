from flask import Flask, send_from_directory, request
from flask_socketio import SocketIO, emit, join_room
import os
import random
import string

app = Flask(__name__)
app.config['SECRET_KEY'] = 'cubewar_secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

GAMES = {}

COLORS = ["#c0392b", "#2980b9", "#27ae60", "#8e44ad",
          "#d35400", "#16a085", "#f39c12", "#e91e63"]

MAX_PLAYERS = 4
ACTIONS_PER_ROUND = 10
ROUND_TIME = 50
PAUSE_TIME = 3
W, H = 800, 800


def generate_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def get_spawn(idx):
    positions = [
        (100, 100),
        (W - 100, 100),
        (100, H - 100),
        (W - 100, H - 100),
    ]
    return positions[idx % len(positions)]


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
        emit('error_msg', {"text": "Только хост может начать"})
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
    """Цикл раундов: ROUND_TIME игры → PAUSE_TIME пауза → снова."""
    while True:
        socketio.sleep(ROUND_TIME)
        if code not in GAMES:
            return
        g = GAMES[code]
        if not g.get("round_active"):
            return
        g["round_active"] = False
        emit('round_ended', {"pause": PAUSE_TIME}, to=code)
        socketio.sleep(PAUSE_TIME)
        if code not in GAMES:
            return
        g = GAMES[code]
        alive = [p for p in g["players"].values() if p["hp"] > 0]
        if len(alive) <= 1:
            return
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
                emit('error_msg', {"text": "Нет действий"})
                return
            p["x"] = data.get("x", p["x"])
            p["y"] = data.get("y", p["y"])
            p["dir"] = data.get("dir", p["dir"])
            p["actions_left"] -= 1
            emit('player_moved', {
                "sid": sid, "x": p["x"], "y": p["y"],
                "dir": p["dir"], "actions_left": p["actions_left"],
            }, to=code)
            break


@socketio.on('shoot')
def on_shoot(data):
    sid = request.sid
    for code, game in GAMES.items():
        if sid in game["players"]:
            p = game["players"][sid]
            if p["hp"] <= 0:
                return
            if not game.get("round_active"):
                return
            if p["actions_left"] <= 0:
                emit('error_msg', {"text": "Нет действий"})
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
            emit('player_hit', {
                "sid": target_sid,
                "hp": p["hp"],
            }, to=code)
            if p["hp"] <= 0:
                emit('player_died', {"sid": target_sid}, to=code)
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
