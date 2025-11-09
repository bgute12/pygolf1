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

MAX_READING = 10  # base max points for distance calculation
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
# Bluetooth Thread
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
# GolfGreen Widget
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
    ball_radius = NumericProperty(6)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(size=self.update_canvas, pos=self.update_canvas)
        Clock.schedule_once(lambda dt: self.update_canvas(), 0)

    def update_canvas(self, *args):
        self.canvas.after.clear()
        with self.canvas.after:
            for hole in self.holes:
                hx, hy = self.get_scaled_hole_pos(hole)
                Color(1, 1, 1, 1)
                Ellipse(pos=(hx - hole["radius"], hy - hole["radius"]),
                        size=(hole["radius"] * 2, hole["radius"] * 2))
            if self.ball_placed:
                Color(1, 1, 1, 1)
                Ellipse(pos=(self.x + self.ball_x - self.ball_radius,
                             self.y + self.ball_y - self.ball_radius),
                        size=(self.ball_radius*2, self.ball_radius*2))

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
        self.ball_placed = False
        self.game_started = False
        for h in HOLES:
            h["last_points"] = None
        self.holes = HOLES.copy()
        self.update_canvas()
        print("Players registered:", self.players)

    def start_game(self):
        if not self.players:
            return
        self.game_started = True
        self.ball_placed = False
        self.current_player_index = 0
        self.current_player = self.players[0]
        self.ball_x = -1000
        self.ball_y = -1000
        self.update_canvas()
        print("Game started. Current player:", self.current_player)

    def next_player(self):
        if not self.players:
            return
        self.current_player_index += 1
        if self.current_player_index >= len(self.players):
            self.current_player_index = 0
            self.current_round += 1
        self.current_player = self.players[self.current_player_index]
        self.update_canvas()
        print(f"Next player: {self.current_player} (Round {self.current_round})")


# -----------------------
# Scoring Helper
# -----------------------
def calculate_points(hole_id, golf_green):
    hole = next((h for h in golf_green.holes if h["id"] == hole_id), None)
    if not hole:
        return 0

    # Use ball position if placed; otherwise center
    hx, hy = golf_green.ball_x, golf_green.ball_y
    if hx < 0 or hy < 0:
        hx = golf_green.width / 2
        hy = golf_green.height / 2

    hole_x, hole_y = golf_green.get_scaled_hole_pos(hole)
    dist = math.hypot(hole_x - hx, hole_y - hy)
    max_diag = math.hypot(golf_green.width, golf_green.height)

    # Points based on distance * hole number
    points = int((dist / max_diag) * MAX_READING * hole_id)

    # If ball is inside the hole → max points
    if dist <= hole["radius"]:
        points = MAX_READING * hole_id

    hole["last_points"] = points
    return points


# -----------------------
# Bluetooth queue processing
# -----------------------
def process_bt_queue(dt):
    golf_green = App.get_running_app().root.ids.get("green")
    while not bt_event_queue.empty():
        hid = bt_event_queue.get_nowait()
        if golf_green and golf_green.current_player:
            pts = calculate_points(hid, golf_green)
            golf_green.player_scores.setdefault(golf_green.current_player, []).append(pts)
            print(f"🏆 {golf_green.current_player} scored {pts} points for hole {hid}")


def start_bt_threads():
    for hid, prefix in HOLE_NAME_PREFIXES.items():
        threading.Thread(target=bt_auto_thread, args=(hid, prefix), daemon=True).start()


# -----------------------
# Root and App
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
