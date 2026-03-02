"""
Flask backend for Instaling Bot Manager web dashboard.
Endpoints:
  GET  /                   -> index.html
  POST /api/start/<bot>    -> start bot  (bot = 'ang' | 'niem')
  POST /api/stop/<bot>     -> stop bot
  GET  /api/stream/<bot>   -> SSE log stream
  GET  /api/status         -> JSON {ang: {running, browser}, niem: ...}
"""

import os, sys, queue, threading, time, json
import importlib.util
from functools import wraps
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin123")

from flask import Flask, Response, jsonify, render_template, request

# ── Resolve paths ─────────────────────────────────────────────────────────────
BASE   = os.path.dirname(os.path.abspath(__file__))
PATHS  = {
    "ang":  os.path.join(BASE, "bot do instalinga"),
    "niem": os.path.join(BASE, "NIEMIECKI"),
}

def load_bot(key: str):
    path = os.path.join(PATHS[key], "bot_engine.py")
    sys.path.insert(0, PATHS[key])
    spec   = importlib.util.spec_from_file_location(f"bot_{key}", path)
    mod    = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.path.pop(0)
    return mod.InstalingBot

BotClasses = {k: load_bot(k) for k in PATHS}

# ── Shared state ──────────────────────────────────────────────────────────────
bots    = {"ang": None,   "niem": None}
running = {"ang": False,  "niem": False}
browser = {"ang": "Google Chrome", "niem": "Google Chrome"}
log_queues: dict[str, list[queue.Queue]] = {"ang": [], "niem": []}

def broadcast(key: str, msg: str):
    ts   = time.strftime("%H:%M:%S")
    line = f"[{ts}]  {msg}"
    for q in log_queues[key]:
        q.put(line)

class RelayQueue:
    def __init__(self, key):
        self.key = key
    def put(self, msg):
        broadcast(self.key, msg)
    def empty(self):
        return True

# ── Authentication ─────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.password != DASHBOARD_PASSWORD:
            return Response(
                'Błędne hasło.', 401,
                {'WWW-Authenticate': 'Basic realm="Login Required"'}
            )
        return f(*args, **kwargs)
    return decorated

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates")

@app.route("/")
@login_required
def index():
    return render_template("index.html")

@app.route("/api/status")
@login_required
def status():
    return jsonify({
        k: {"running": running[k], "browser": browser[k]}
        for k in ("ang", "niem")
    })

@app.route("/api/start/<bot>", methods=["POST"])
@login_required
def start_bot(bot):
    if bot not in PATHS:
        return jsonify(error="Unknown bot"), 400
    if running[bot]:
        return jsonify(ok=False, msg="Already running")

    data = request.get_json(silent=True) or {}
    browser[bot] = data.get("browser", "Google Chrome")

    # Get credentials from .env
    login = os.getenv(f"INSTALING_LOGIN_{bot.upper()}")
    password = os.getenv(f"INSTALING_PASS_{bot.upper()}")

    bots[bot]    = BotClasses[bot](RelayQueue(bot), browser[bot], login=login, password=password)
    running[bot] = True
    broadcast(bot, f"▶ Bot uruchomiony ({browser[bot]})…")

    def run_bot():
        bots[bot].run()
        running[bot] = False
        broadcast(bot, "■ Bot zakończył działanie.")

    threading.Thread(target=run_bot, daemon=True).start()
    return jsonify(ok=True)

@app.route("/api/stop/<bot>", methods=["POST"])
@login_required
def stop_bot(bot):
    if bot not in PATHS:
        return jsonify(error="Unknown bot"), 400
    if bots[bot]:
        bots[bot].stop()
    running[bot] = False
    broadcast(bot, "■ Bot zatrzymany przez użytkownika.")
    return jsonify(ok=True)

@app.route("/api/stream/<bot>")
@login_required
def stream(bot):
    if bot not in PATHS:
        return Response("data: unknown bot

", mimetype="text/event-stream")

    client_q: queue.Queue = queue.Queue()
    log_queues[bot].append(client_q)

    def generate():
        try:
            yield "data: ✅ Połączono z logami

"
            while True:
                try:
                    line = client_q.get(timeout=25)
                    yield f"data: {line}

"
                except queue.Empty:
                    yield ": heartbeat

"
        except GeneratorExit:
            pass
        finally:
            if client_q in log_queues[bot]:
                log_queues[bot].remove(client_q)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    print("=================================================")
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", debug=False, threaded=True, port=port)
