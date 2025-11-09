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

MIN_READING = 0
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
                    # When a hit is detected, queue it for processing
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
    ball_radius = NumericProperty(6)
    
    def update_scores_display(self):
        if self.parent and self.parent.parent:  # RootWidget exists
            try:
                players_label = self.parent.parent.ids.players_label
                players_label.text = '\n'.join(
                    [f"{p}: {self.get_player_score(p)}" for p in self.players]
                )
            except Exception as e:
                print("Error updating scores:", e)


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

        # Update hole labels
        try:
            root = App.get_running_app().root
            if root and hasattr(root, 'ids'):
                for i, hole in enumerate(self.holes, start=1):
                    hid = f"h{i}"
                    lbl = root.ids.get(hid)
                    if lbl:
                        hx, hy = self.get_scaled_hole_pos(hole)
                        lbl.pos = (hx - lbl.width / 2, hy + 12)
                        lp = hole.get("last_points")
                        lbl.text = f"H{i}: {lp if lp is not None else '-'}"
        except Exception:
            pass

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

    def get_player_score(self, player):
        scores = self.player_scores.get(player, [])
        return sum(scores) if scores else 0

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

    def replace_ball(self):
        if not self.game_started or self.current_player_index != 0:
            return
        self.ball_placed = False
        self.ball_x = -1000
        self.ball_y = -1000
        for h in self.holes:
            h["last_points"] = None
        self.update_canvas()
        print("Ball replaced for re-placement by first player")

    def next_player(self):
        if not self.players:
            return
        self.current_player_index += 1
        if self.current_player_index >= len(self.players):
            self.current_player_index = 0
            self.current_round += 1
            for h in self.holes:
                h["last_points"] = None
            self.ball_placed = False
            self.ball_x = -1000
            self.ball_y = -1000
        self.current_player = self.players[self.current_player_index]
        self.update_canvas()
        print(f"Next player: {self.current_player} (Round {self.current_round})")

    def clear_scores(self):
        self.player_scores = {p: [] for p in self.players}
        self.update_canvas()

    def on_touch_down(self, touch):
        if not (self.mode_selected and self.mode == "Normal" and self.game_started):
            return False
        root = App.get_running_app().root
        side = root.ids.get("side_panel", None)
        if side and side.collide_point(*touch.pos):
            return False
        if not self.collide_point(*touch.pos):
            return False
        if self.ball_placed:
            print("Ball already placed for this round; ignore touch")
            return True
        self._touch_x = touch.x - self.x
        self._touch_y = touch.y - self.y
        Clock.schedule_once(self._place_ball, 0.05)
        return True

    def _place_ball(self, dt):
        if self.ball_placed:
            return
        local_x = getattr(self, "_touch_x", None)
        local_y = getattr(self, "_touch_y", None)
        if local_x is None or local_y is None:
            return

        max_diag = math.hypot(max(1, self.width), max(1, self.height))
        nearest_hole = None
        points_for_hole = 0

        for hole in self.holes:
            hx, hy = self.get_scaled_hole_pos(hole)
            dist = math.hypot(hx - self.x - local_x, hy - self.y - local_y)

            if dist <= hole["radius"]:
                # Ball goes in the hole → max points
                pts = MAX_READING
                nearest_hole = hole
            else:
                # Farther away = more points
                pts = int((dist / max_diag) * MAX_READING)
            hole["last_points"] = pts

            if pts > points_for_hole:
                points_for_hole = pts
                nearest_hole = hole if dist <= hole["radius"] else nearest_hole

        # Update current player's score if ball goes in
        if self.current_player and nearest_hole and math.hypot(
                self.get_scaled_hole_pos(nearest_hole)[0] - self.x - local_x,
                self.get_scaled_hole_pos(nearest_hole)[1] - self.y - local_y
        ) <= nearest_hole["radius"]:
            self.player_scores.setdefault(self.current_player, []).append(points_for_hole)
            print(f"🏆 {self.current_player} scored {points_for_hole} points for hole {nearest_hole['id']}")

        # Set ball visual
        self.ball_x = local_x
        self.ball_y = local_y
        self.ball_placed = True
        self.update_canvas()


# -----------------------
# Bluetooth integration
# -----------------------
def process_bt_queue(dt):
    app = App.get_running_app()
    while not bt_event_queue.empty():
        hid = bt_event_queue.get_nowait()
        print(f"[BT EVENT] Hole {hid} triggered")


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