#!/usr/bin/env python3
import math
import threading
import time
import subprocess
import serial
from queue import Queue

from kivy.app import App
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.properties import ListProperty, NumericProperty, StringProperty, DictProperty, BooleanProperty
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

# Device name prefixes for each hole’s ESP32/HC-05 module
HOLE_NAME_PREFIXES = {
    1: "HOLE_1",
    2: "HOLE_2",
    3: "HOLE_3",
    4: "HOLE_4",
    5: "HOLE_5",
}

BT_RETRY_DELAY = 5  # seconds
bt_event_queue = Queue()

# -----------------------
# Utility: run shell cmd
# -----------------------
def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip()
    except Exception as e:
        print("⚠️", e)
        return ""

# -----------------------
# Auto Bluetooth Thread
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
                print(f"[BT] ❌ {name_prefix} not found; retrying in {BT_RETRY_DELAY}s")
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

            buffer = b""
            while True:
                data = ser.readline()
                if not data:
                    continue
                msg = data.decode(errors="ignore").strip()
                if msg:
                    print(f"[BT][{name_prefix}] {msg}")
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

# -----------------------
# Kivy Game Classes
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
    mode = StringProperty("Normal")
    mode_selected = BooleanProperty(True)
    game_started = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(size=self.update_canvas, pos=self.update_canvas)
        Clock.schedule_once(lambda dt: self.update_canvas(), 0)

    def update_canvas(self, *args):
        self.canvas.after.clear()
        with self.canvas.after:
            # Draw holes
            for hole in self.holes:
                hx, hy = self.get_scaled_hole_pos(hole)
                Color(1, 1, 1, 1)
                Ellipse(pos=(hx - hole["radius"], hy - hole["radius"]), size=(hole["radius"]*2, hole["radius"]*2))
            # Draw ball
            if self.ball_placed:
                Color(1, 1, 1, 1)
                Ellipse(pos=(self.x + self.ball_x - 6, self.y + self.ball_y - 6), size=(12, 12))

    def get_scaled_hole_pos(self, hole):
        phx, phy = hole.get("pos_hint", (0.5, 0.5))
        px = self.x + phx * max(1, self.width)
        py = self.y + phy * max(1, self.height)
        return px, py

    def register_players(self, count=2):
        self.players = [f"Player {i+1}" for i in range(count)]
        self.player_scores = {p: [] for p in self.players}
        self.current_player_index = 0
        self.current_round = 1
        self.current_player = self.players[0]
        self.game_started = True
        print("Players registered:", self.players)

    def get_player_score(self, player):
        scores = self.player_scores.get(player, [])
        return sum(scores) if scores else 0

    def next_player(self):
        if not self.players:
            return
        self.current_player_index += 1
        if self.current_player_index >= len(self.players):
            self.current_player_index = 0
            self.current_round += 1
        self.current_player = self.players[self.current_player_index]
        print(f"➡️ Next: {self.current_player} (Round {self.current_round})")

    def handle_hole_event(self, hole_id):
        hole = next((h for h in self.holes if h["id"] == hole_id), None)
        if not hole:
            print(f"Unknown hole {hole_id}")
            return
        hx, hy = self.get_scaled_hole_pos(hole)
        # Place ball with a short delay
        Clock.schedule_once(lambda dt: self.place_ball(hx, hy, hole_id), 0.5)

    def place_ball(self, hx, hy, hole_id):
        self.ball_x, self.ball_y, self.ball_placed = hx - self.x, hy - self.y, True
        if self.current_player:
            self.player_scores.setdefault(self.current_player, []).append(MAX_READING)
            print(f"🏆 {self.current_player} scored {MAX_READING} at hole {hole_id}")
        Clock.schedule_once(lambda dt: self.next_player(), 1)
        self.update_canvas()

    def clear_scores(self):
        self.player_scores = {p: [] for p in self.players}
        self.ball_placed = False
        self.ball_x, self.ball_y = -1000, -1000
        self.update_canvas()

    def start_game(self):
        self.game_started = True
        self.current_round = 1
        if self.players:
            self.current_player_index = 0
            self.current_player = self.players[0]

class RootWidget(BoxLayout):
    pass

# -----------------------
# Bluetooth integration
# -----------------------
def process_bt_queue(dt):
    app = App.get_running_app()
    while not bt_event_queue.empty():
        hid = bt_event_queue.get_nowait()
        Clock.schedule_once(lambda dt, hole=hid: app.green.handle_hole_event(hole), 0)

def start_bt_threads():
    for hid, prefix in HOLE_NAME_PREFIXES.items():
        threading.Thread(target=bt_auto_thread, args=(hid, prefix), daemon=True).start()

# -----------------------
# Kivy App
# -----------------------
class MiniGolfApp(App):
    def build(self):
        Builder.load_file("minigolf.kv")  # Load your KV file
        self.green = RootWidget().ids.golf  # Access the GolfGreen inside RootWidget
        Clock.schedule_interval(process_bt_queue, 0.1)
        start_bt_threads()
        return RootWidget()

    def on_start(self):
        # Register default 2 players
        self.green.register_players(2)

# -----------------------
if __name__ == "__main__":
    MiniGolfApp().run()
