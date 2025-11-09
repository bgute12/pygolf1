#!/usr/bin/env python3
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
    {"id": 1, "pos_hint": (0.0913, 0.6378), "radius": 8, "points": 5, "last_points": None},
    {"id": 2, "pos_hint": (0.3620, 0.7678), "radius": 8, "points": 3, "last_points": None},
    {"id": 3, "pos_hint": (0.1985, 0.2817), "radius": 8, "points": 2, "last_points": None},
    {"id": 4, "pos_hint": (0.7452, 0.2276), "radius": 8, "points": 0, "last_points": None},
    {"id": 5, "pos_hint": (0.9331, 0.3715), "radius": 8, "points": 4, "last_points": None},
]

MAX_PLAYERS = 3
MAX_ROUNDS = 10

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
            print(f"[BT] Scanning for {name_prefix}...")
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
                print(f"[BT] {name_prefix} not found, retrying in {BT_RETRY_DELAY}s")
                time.sleep(BT_RETRY_DELAY)
                continue

            print(f"[BT] Found {name_prefix} at {addr}")
            run_cmd(f"bluetoothctl pair {addr}")
            run_cmd(f"bluetoothctl trust {addr}")
            run_cmd(f"bluetoothctl connect {addr}")
            run_cmd(f"sudo rfcomm release {hole_id} || true")
            run_cmd(f"sudo rfcomm bind {hole_id} {addr} 1")

            ser = None
            for _ in range(3):
                try:
                    ser = serial.Serial(port, 9600, timeout=1)
                    break
                except Exception:
                    time.sleep(1)

            if not ser:
                time.sleep(BT_RETRY_DELAY)
                continue

            while True:
                data = ser.readline()
                if not data:
                    continue
                msg = data.decode(errors="ignore").strip()
                if msg:
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
    holes = ListProperty(HOLES.copy())
    ball_x = NumericProperty(-1000)
    ball_y = NumericProperty(-1000)
    ball_placed = BooleanProperty(False)
    game_started = BooleanProperty(False)

    def register_players(self, count=2):
        # clamp player count
        count = max(1, min(count, MAX_PLAYERS))
        self.players = [f"Player {i+1}" for i in range(count)]
        self.player_scores = {p: [] for p in self.players}
        self.current_player_index = 0
        self.current_player = self.players[0]
        self.game_started = False
        print("Players registered:", self.players)

    def start_game(self):
        if not self.players:
            return
        self.game_started = True
        self.current_player_index = 0
        self.current_player = self.players[0]
        print("Game started. Current player:", self.current_player)

    def next_player(self):
        if not self.players:
            return
        self.current_player_index += 1
        if self.current_player_index >= len(self.players):
            self.current_player_index = 0
            self.current_round += 1
        self.current_player = self.players[self.current_player_index]
        print(f"Next player: {self.current_player} (Round {self.current_round})")


# -----------------------
# Bluetooth queue processing
# -----------------------
def process_bt_queue(dt):
    golf_green = App.get_running_app().root.ids.get("green")
    while not bt_event_queue.empty():
        hid = bt_event_queue.get_nowait()
        if golf_green and golf_green.current_player:
            hole = next((h for h in golf_green.holes if h["id"] == hid), None)
            if hole:
                pts = hole["points"]
                golf_green.player_scores.setdefault(golf_green.current_player, []).append(pts)
                print(f"{golf_green.current_player} scored {pts} points for hole {hid}")


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
