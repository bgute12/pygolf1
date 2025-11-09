# minigolf_with_bt.py
import math
import threading
import time
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

# Hole names for BT scanning
HOLE_NAME_PREFIXES = {
    1: "HOLE_1",
    2: "HOLE_2",
    3: "HOLE_3",
    4: "HOLE_4",
    5: "HOLE_5",
}

# Bluetooth reconnect delay (seconds)
BT_RETRY_DELAY = 5

# Queue for passing BT events to Kivy main thread
bt_event_queue = Queue()

# -----------------------
# Kivy GUI / Game Code
# -----------------------
class GolfGreen(Widget):
    players = ListProperty([])
    current_player_index = NumericProperty(0)
    current_round = NumericProperty(1)
    current_player = StringProperty("")
    player_scores = DictProperty({})
    live_text = StringProperty("")
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
            for hole in self.holes:
                hx, hy = self.get_scaled_hole_pos(hole)
                Color(1, 1, 1, 1)
                Ellipse(pos=(hx - hole["radius"], hy - hole["radius"]),
                        size=(hole["radius"] * 2, hole["radius"] * 2))
            if self.ball_placed:
                Color(1, 1, 1, 1)
                Ellipse(pos=(self.x + self.ball_x - 10, self.y + self.ball_y - 10), size=(10, 10))

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
        self.update_canvas()

    def start_game(self):
        if not self.players:
            return
        self.game_started = True
        self.ball_placed = False
        self.current_player_index = 0
        self.current_player = self.players[self.current_player_index]
        self.update_canvas()

    def next_player(self):
        if not self.players:
            return
        self.current_player_index += 1
        if self.current_player_index >= len(self.players):
            self.current_player_index = 0
            self.current_round += 1
            if self.current_round > MAX_ROUNDS:
                return
            self.ball_placed = False
            self.ball_x = -1000
            self.ball_y = -1000
        self.current_player = self.players[self.current_player_index]
        self.update_canvas()

    def clear_scores(self):
        self.player_scores = {p: [] for p in self.players}
        self.update_canvas()

    def get_scaled_hole_pos(self, hole):
        phx, phy = hole.get("pos_hint", (0.5, 0.5))
        px = self.x + phx * max(0, self.width)
        py = self.y + phy * max(0, self.height)
        return px, py

    def handle_hole_event(self, hole_id):
        hole = next((h for h in self.holes if h["id"] == hole_id), None)
        if not hole:
            return
        hx, hy = self.get_scaled_hole_pos(hole)
        self.ball_x = hx - self.x
        self.ball_y = hy - self.y
        self.ball_placed = True
        if self.current_player:
            self.player_scores.setdefault(self.current_player, []).append(MAX_READING)
        Clock.schedule_once(lambda dt: self.next_player(), 1.0)
        self.update_canvas()


class RootWidget(BoxLayout):
    pass


class MiniGolfApp(App):
    def build(self):
        root = RootWidget()
        self.green = root.ids.get("golf")
        # start Bluetooth polling
        Clock.schedule_interval(self.process_bt_queue, 0.1)
        return root

    def on_start(self):
        if self.green:
            self.green.register_players(2)
            self.green.start_game()
        # start BT threads for each hole
        start_bluetooth_threads(self.on_bt_event)

    def on_bt_event(self, hole_id):
        if self.green:
            self.green.handle_hole_event(hole_id)

    def process_bt_queue(self, dt):
        while not bt_event_queue.empty():
            try:
                hole_id = bt_event_queue.get_nowait()
                Clock.schedule_once(lambda dt, hid=hole_id: self.on_bt_event(hid), 0)
            except Exception as e:
                print("Error processing BT queue:", e)


# -----------------------
# Bluetooth background code
# -----------------------
def bt_listen_thread(hole_id, name_prefix, callback):
    """
    Thread: simulate connecting to device with name_prefix.
    Pushes events into bt_event_queue.
    Replace this with your working BT code.
    """
    import random
    while True:
        # simulate a hole trigger randomly every 10-30s
        time.sleep(random.randint(10, 30))
        print(f"[BT] Simulated event: Hole {hole_id}")
        bt_event_queue.put(hole_id)


def start_bluetooth_threads(main_thread_callback):
    for hole_id, prefix in HOLE_NAME_PREFIXES.items():
        t = threading.Thread(target=bt_listen_thread, args=(hole_id, prefix, main_thread_callback), daemon=True)
        t.start()


if __name__ == "__main__":
    MiniGolfApp().run()
