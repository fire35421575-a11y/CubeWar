from flask import Flask, send_from_directory, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import os
import random
import string

app = Flask(__name__)
app.config['SECRET_KEY'] = 'cubewar_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*")

# активные игры: room_code -> { players: {sid: {name, x, y, dir, hp}} }
GAMES = {}

COLORS = ["#c0392b", "#2980b9", "#27ae60", "#8e44ad", "#d35400", "#16a085", "#f39c12", "#e91e63"]


def generate_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


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
        "players": {
            sid: {
                "name": name,
                "x": 300, "y": 300,
                "dir": {"x": 1, "y": 0},
                "hp": 100,
                "color": COLORS[0],
            }
        }
    }
    join_room(code)
    emit('game_created', {"code": code, "color": COLORS[0]})


@socketio.on('join_game')
def on_join(data):
    code = data.get('code', '').upper()
    sid = request.sid
    name = data.get('name', 'Игрок')[:12]
    if code not in GAMES:
        emit('error_msg', {"text": "Комната не найдена"})
        return
    game = GAMES[code]
    if len(game["players"]) >= 8:
        emit('error_msg', {"text": "Комната полна"})
        return
    if sid in game["players"]:
        emit('error_msg', {"text": "Ты уже в комнате"})
        return

    idx = len(game["players"])
    # позиция в углу
    positions = [(100, 100), (500, 100), (100, 500), (500, 500),
                 (300, 100), (300, 500), (100, 300), (500, 300)]
    px, py = positions[idx % len(positions)]

    game["players"][sid] = {
        "name": name,
        "x": px, "y": py,
        "dir": {"x": 1, "y": 0},
        "hp": 100,
        "color": COLORS[idx % len(COLORS)],
    }

    join_room(code)
    # отдаём новому — всех игроков
    emit('joined', {
        "code": code,
        "players": game["players"],
        "my_color": COLORS[idx % len(COLORS)],
    })
    # всем остальным — нового игрока
    emit('player_joined', {
        "sid": sid,
        "player": game["players"][sid],
    }, to=code, include_self=False)


@socketio.on('move')
def on_move(data):
    sid = request.sid
    # ищем игру, где этот sid
    for code, game in GAMES.items():
        if sid in game["players"]:
            p = game["players"][sid]
            p["x"] = data.get("x", p["x"])
            p["y"] = data.get("y", p["y"])
            p["dir"] = data.get("dir", p["dir"])
            emit('player_moved', {
                "sid": sid,
                "x": p["x"], "y": p["y"],
                "dir": p["dir"],
            }, to=code, include_self=False)
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
            break


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
