import math
import threading
import time
import subprocess
import serial
from queue import Queue

from kivy.app import App
from kivy.clock import Clock
from kivy.properties import (
    ListProperty, NumericProperty, StringProperty, DictProperty, BooleanProperty
)
from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout
from kivy.graphics import Color, Ellipse

# -----------------------
# Config
# -----------------------
HOLES = [
    {"id": 1, "pos_hint": (0.0913, 0.6378), "radius": 8, "last_points": None},
    {"id": 2, "pos_hint": (0.3620, 0.7678), "radius": 8, "last_points": None},
    {"id": 3, "pos_hint": (0.1985, 0.2817), "radius": 8, "last_points": None},
    {"id": 4, "pos_hint": (0.7452, 0.2276), "radius": 8, "last_points": None},
    {"id": 5, "pos_hint": (0.9331, 0.3715), "radius": 8, "last_points": None},
]

MIN_READING = 0
MAX_READING = 10
MAX_PLAYERS = 3
MAX_ROUNDS = 10

# Bluetooth settings
HOLE_NAME_PREFIXES = {
    1: "HOLE_1",
    2: "HOLE_2",
    3: "HOLE_3",
    4: "HOLE_4",
    5: "HOLE_5",
}
BT_RETRY_DELAY = 5
bt_event_queue = Queue()

# -----------------------
# Utility function
# -----------------------
def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip()
    except Exception as e:
        print("⚠️", e)
        return ""

# -----------------------
# Bluetooth thread
# -----------------------
def bt_auto_thread(hole_id, name_prefix):
    port = f"/dev/rfcomm{hole_id}"
    while True:
        try:
            print(f"[BT] 🔍 Scanning for {name_prefix}...")
            run_cmd("bluetoothctl scan on &")
            time.sleep(6)
            devices = run_cmd("bluetoothctl devices")
            run_cmd("bluetoothctl scan off")

            addr = None
            for line in devices.splitlines():
                if name_prefix in line:
                    addr = line.split()[1]
                    break

            if not addr:
                print(f"[BT] ❌ {name_prefix} not found, retrying in {BT_RETRY_DELAY}s")
                time.sleep(BT_RETRY_DELAY)
                continue

            print(f"[BT] ✅ Found {name_prefix} at {addr}")
            run_cmd(f"bluetoothctl pair {addr}")
            run_cmd(f"bluetoothctl trust {addr}")
            run_cmd(f"bluetoothctl connect {addr}")
            run_cmd(f"sudo rfcomm release {hole_id} || true")
            run_cmd(f"sudo rfcomm bind {hole_id} {addr} 1")
            print(f"[BT] 🔗 Bound {addr} -> {port}")

            ser = None
            for _ in range(3):
                try:
                    ser = serial.Serial(port, 9600, timeout=1)
                    print(f"[BT] 💬 Listening on {port}")
                    break
                except Exception:
                    time.sleep(1)

            if not ser:
                print(f"[BT] ⚠️ Cannot open {port}, retrying...")
                time.sleep(BT_RETRY_DELAY)
                continue

            while True:
                data = ser.readline()
                if not data:
                    continue
                msg = data.decode(errors="ignore").strip()
                if msg:
                    print(f"[BT][{name_prefix}] {msg}")
                    # message format: "HOLE:<hole_id>:1"
                    parts = msg.split(":")
                    if len(parts) >= 3 and parts[0] == "HOLE":
                        try:
                            hid = int(parts[1])
                            if parts[2].startswith("1"):
                                bt_event_queue.put(hid)
                        except ValueError:
                            pass
        except Exception as e:
            print(f"[BT] Exception ({name_prefix}):", e)
        finally:
            run_cmd(f"sudo rfcomm release {hole_id} || true")
            time.sleep(BT_RETRY_DELAY)

def process_bt_queue(dt):
    app = App.get_running_app()
    while not bt_event_queue.empty():
        hid = bt_event_queue.get_nowait()
        # schedule ball placement in Kivy
        Clock.schedule_once(lambda dt, hole_id=hid: app.root.ids.golf.handle_bt_hole(hole_id), 0)

def start_bt_threads():
    for hid, prefix in HOLE_NAME_PREFIXES.items():
        threading.Thread(target=bt_auto_thread, args=(hid, prefix), daemon=True).start()

# -----------------------
# GolfGreen
# -----------------------
class GolfGreen(Widget):
    players = ListProperty([])
    current_player_index = NumericProperty(0)
    current_round = NumericProperty(1)
    current_player = StringProperty("")
    player_scores = DictProperty({})
    ball_x = NumericProperty(-1000)
    ball_y = NumericProperty(-1000)
    holes = ListProperty(HOLES.copy())
    ball_placed = BooleanProperty(False)
    game_started = BooleanProperty(False)

    ball_radius = NumericProperty(6)
    _accept_touches = False
    mode_selected = BooleanProperty(True)
    mode = StringProperty("Normal")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(size=self.update_canvas, pos=self.update_canvas)
        Clock.schedule_once(self._enable_touches, 0.5)
        Clock.schedule_once(lambda dt: self.update_canvas(), 0)

    def _enable_touches(self, dt):
        self._accept_touches = True

    def update_canvas(self, *args):
        self.canvas.after.clear()
        with self.canvas.after:
            for hole in self.holes:
                hx, hy = self.get_scaled_hole_pos(hole)
                Color(1, 1, 1, 1)
                Ellipse(pos=(hx - hole["radius"], hy - hole["radius"]),
                        size=(hole["radius"]*2, hole["radius"]*2))
            if self.ball_placed:
                Color(1, 1, 1, 1)
                Ellipse(pos=(self.x + self.ball_x - self.ball_radius,
                             self.y + self.ball_y - self.ball_radius),
                        size=(self.ball_radius*2, self.ball_radius*2))

        try:
            root = App.get_running_app().root
            if root and hasattr(root, 'ids'):
                for i, hole in enumerate(self.holes, start=1):
                    lbl = root.ids.get(f"h{i}")
                    if lbl:
                        hx, hy = self.get_scaled_hole_pos(hole)
                        lbl.pos = (hx - lbl.width/2, hy + 12)
                        lp = hole.get("last_points")
                        lbl.text = f"H{i}: {lp if lp is not None else '-'}"
        except Exception:
            pass

    def get_scaled_hole_pos(self, hole):
        phx, phy = hole.get("pos_hint", (0.5, 0.5))
        px = self.x + phx * max(1, self.width)
        py = self.y + phy * max(1, self.height)
        return px, py

    def get_player_score(self, name):
        scores = self.player_scores.get(name, [])
        return sum(scores) if scores else 0

    def register_players(self, count=1):
        count = max(1, min(count, MAX_PLAYERS))
        self.players = [f"Player {i+1}" for i in range(count)]
        self.player_scores = {p: [] for p in self.players}
        self.current_player_index = 0
        self.current_round = 1
        self.current_player = self.players[0] if self.players else ""
        self.ball_placed = False
        self.game_started = False
        self.holes = [{**h, "last_points": None} for h in HOLES]
        self.update_canvas()
        print("Registered players:", self.players)

    def start_game(self):
        if not self.players:
            return
        self.game_started = True
        self.current_player_index = 0
        self.current_player = self.players[0]
        self.ball_x = -1000
        self.ball_y = -1000
        self.ball_placed = False
        self.update_canvas()
        print("Game started. Current player:", self.current_player)

    def handle_bt_hole(self, hole_id):
        """Called when Bluetooth event triggers a hole hit"""
        if self.ball_placed:
            print("Ball already placed, ignoring BT event.")
            return
        hx, hy = self.get_scaled_hole_pos(next(h for h in self.holes if h["id"] == hole_id))
        self.ball_x = hx - self.x
        self.ball_y = hy - self.y
        self.ball_placed = True
        if self.current_player:
            self.player_scores.setdefault(self.current_player, []).append(MAX_READING)
        print(f"[BT] Ball placed automatically for player {self.current_player} at hole {hole_id}")
        self.update_canvas()

    def replace_ball(self):
        if not self.game_started or self.current_player_index != 0:
            return
        self.ball_x = -1000
        self.ball_y = -1000
        self.ball_placed = False
        self.holes = [{**h, "last_points": None} for h in HOLES]
        self.update_canvas()
        print("Ball replaced for first player.")

    def next_player(self):
        if not self.players:
            return
        self.current_player_index += 1
        if self.current_player_index >= len(self.players):
            self.current_player_index = 0
            self.current_round += 1
            self.ball_placed = False
            self.ball_x = -1000
            self.ball_y = -1000
            self.holes = [{**h, "last_points": None} for h in HOLES]
        self.current_player = self.players[self.current_player_index]
        self.update_canvas()
        print(f"Next player: {self.current_player} (Round {self.current_round})")

# -----------------------
# Kivy App
# -----------------------
class RootWidget(BoxLayout):
    pass

class MiniGolfApp(App):
    def build(self):
        Clock.schedule_interval(process_bt_queue, 0.1)
        start_bt_threads()
        return RootWidget()

if __name__ == "__main__":
    MiniGolfApp().run()
