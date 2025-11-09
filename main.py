# minigolf_full_bt.py
import math
import threading
import time
from queue import Queue

from kivy.app import App
from kivy.clock import Clock
from kivy.properties import ListProperty, NumericProperty, StringProperty, DictProperty, BooleanProperty
from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout
from kivy.graphics import Color, Ellipse, Rectangle

import socket  # classic Bluetooth RFCOMM (serial-like)

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

# Bluetooth devices: map hole ID → device name
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
# Golf Green Widget
# -----------------------
class GolfGreen(Widget):
    players = ListProperty([])
    current_player_index = NumericProperty(0)
    current_round = NumericProperty(1)
    current_player = StringProperty("")
    player_scores = DictProperty({})
    live_points_by_hole = DictProperty({})
    ball_x = NumericProperty(-1000)
    ball_y = NumericProperty(-1000)
    holes = ListProperty(HOLES.copy())
    ball_placed = BooleanProperty(False)
    mode = StringProperty("")
    mode_selected = BooleanProperty(False)
    game_started = BooleanProperty(False)

    _accept_touches = False

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
            # draw holes
            for hole in self.holes:
                hx, hy = self.get_scaled_hole_pos(hole)
                Color(1, 1, 1, 1)
                Ellipse(pos=(hx - hole["radius"], hy - hole["radius"]),
                        size=(hole["radius"] * 2, hole["radius"] * 2))
            # draw ball
            if self.ball_placed:
                Color(1, 1, 1, 1)
                Ellipse(pos=(self.x + self.ball_x - 5, self.y + self.ball_y - 5), size=(10, 10))

    def get_scaled_hole_pos(self, hole):
        phx, phy = hole.get("pos_hint", (0.5, 0.5))
        px = self.x + phx * max(0, self.width)
        py = self.y + phy * max(0, self.height)
        return px, py

    # --- player management ---
    def register_players(self, count=1):
        count = max(1, min(count, MAX_PLAYERS))
        self.players = [f"Player {i+1}" for i in range(count)]
        self.player_scores = {p: [] for p in self.players}
        self.current_player_index = 0
        self.current_round = 1
        self.current_player = self.players[0] if self.players else ""
        self.ball_placed = False
        self.game_started = False
        self.update_canvas()
        print("Registered players:", self.players)

    def start_game(self):
        if not self.players:
            print("No players to start")
            return
        self.game_started = True
        self.ball_placed = False
        self.current_player_index = 0
        self.current_player = self.players[self.current_player_index]
        self.update_canvas()
        print("Game started. Current player:", self.current_player)

    def next_player(self):
        if not self.players:
            return
        self.current_player_index += 1
        if self.current_player_index >= len(self.players):
            self.current_player_index = 0
            self.current_round += 1
            if self.current_round > MAX_ROUNDS:
                print("Game finished")
                return
            self.ball_placed = False
            self.ball_x = -1000
            self.ball_y = -1000
        self.current_player = self.players[self.current_player_index]
        self.update_canvas()
        print(f"➡️ Next: {self.current_player} (Round {self.current_round})")

    def get_player_score(self, name):
        return sum(self.player_scores.get(name, []))

    def clear_scores(self):
        self.player_scores = {p: [] for p in self.players}
        self.update_canvas()

    # --- ball placement ---
    def on_touch_down(self, touch):
        if not self._accept_touches:
            return True
        if not (self.mode_selected and self.mode == "Normal" and self.game_started):
            return False
        if not self.collide_point(*touch.pos):
            return False
        if self.ball_placed:
            return True
        local_x = touch.x - self.x
        local_y = touch.y - self.y
        self._touch_x = local_x
        self._touch_y = local_y
        Clock.schedule_once(self._place_ball, 0.3)  # delay
        return True

    def _place_ball(self, dt):
        if self.ball_placed:
            return
        local_x = getattr(self, "_touch_x", None)
        local_y = getattr(self, "_touch_y", None)
        if local_x is None or local_y is None:
            return
        max_dist = math.hypot(max(1, self.width), max(1, self.height))
        results = []
        for i, hole in enumerate(self.holes):
            hx, hy = self.get_scaled_hole_pos(hole)
            dist = math.hypot(hx - self.x - local_x, hy - self.y - local_y)
            pts = int(round(MIN_READING + min(1.0, dist/max_dist)*(MAX_READING-MIN_READING)))
            new_h = hole.copy()
            new_h["last_points"] = pts
            self.holes[i] = new_h
            results.append((new_h["id"], pts))
            self.live_points_by_hole[new_h["id"]] = pts
        nearest = min(results, key=lambda t: t[1])
        if self.current_player:
            score = MAX_READING if nearest[1]==0 else 0
            self.player_scores.setdefault(self.current_player, []).append(score)
            print(f"🏆 {self.current_player} scored {score} at hole {nearest[0]}")
        self.ball_x = local_x
        self.ball_y = local_y
        self.ball_placed = True
        self.update_canvas()

    # --- handle BT events ---
    def handle_hole_event(self, hole_id):
        hole = next((h for h in self.holes if h["id"]==hole_id), None)
        if not hole:
            print("Unknown hole", hole_id)
            return
        hx, hy = self.get_scaled_hole_pos(hole)
        self.ball_x = hx - self.x
        self.ball_y = hy - self.y
        self.ball_placed = True
        if self.current_player:
            self.player_scores.setdefault(self.current_player, []).append(MAX_READING)
            print(f"🏆 {self.current_player} scored {MAX_READING} at hole {hole_id}")
        Clock.schedule_once(lambda dt: self.next_player(), 1.0)
        self.update_canvas()


# -----------------------
# Root + App
# -----------------------
class RootWidget(BoxLayout):
    pass

class MiniGolfApp(App):
    def build(self):
        root = RootWidget()
        self.green = root.ids.get("golfgreen") or root.children[0]
        return root

    def on_start(self):
        if self.green:
            self.green.register_players(2)
            self.green.start_game()
        start_bluetooth_threads(self.on_bt_event)

    def on_bt_event(self, hole_id):
        if self.green:
            self.green.handle_hole_event(hole_id)


# -----------------------
# Classic Bluetooth Listener (simulate RFCOMM)
# -----------------------
def bt_listen_thread(hole_id, name_prefix):
    while True:
        try:
            print(f"[BT] 🔍 Scanning for {name_prefix}...")
            # Simulate discovering device
            found = True
            if not found:
                print(f"[BT] ❌ {name_prefix} not found; retrying in {BT_RETRY_DELAY}s")
                time.sleep(BT_RETRY_DELAY)
                continue
            # Simulate event every few seconds
            time.sleep(5 + hole_id)
            print(f"[BT][{name_prefix}] HOLE:{hole_id}:1")
            bt_event_queue.put(hole_id)
        except Exception as e:
            print("[BT] Exception:", e)
        time.sleep(BT_RETRY_DELAY)


def start_bluetooth_threads(main_callback):
    for hole_id, prefix in HOLE_NAME_PREFIXES.items():
        t = threading.Thread(target=bt_listen_thread, args=(hole_id, prefix), daemon=True)
        t.start()
    Clock.schedule_interval(process_bt_queue, 0.1)


def process_bt_queue(dt):
    app = App.get_running_app()
    while not bt_event_queue.empty():
        try:
            hole_id = bt_event_queue.get_nowait()
            Clock.schedule_once(lambda dt, hid=hole_id: app.on_bt_event(hid), 0)
        except Exception as e:
            print("Error processing BT queue:", e)


if __name__ == "__main__":
    MiniGolfApp().run()
