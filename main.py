# minigolf_with_bt_serial.py
import math
import threading
import time
from queue import Queue
import serial  # For serial-based Bluetooth

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

# Serial ports for each hole
SERIAL_PORTS = {
    1: "/dev/ttyUSB0",
    2: "/dev/ttyUSB1",
    3: "/dev/ttyUSB2",
    4: "/dev/ttyUSB3",
    5: "/dev/ttyUSB4",
}
SERIAL_BAUD = 9600

bt_event_queue = Queue()

# -----------------------
# Kivy GolfGreen
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

    def get_player_score(self, name):
        """Return total score for a player"""
        return sum(self.player_scores.get(name, []))

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
                # smaller ball
                Ellipse(pos=(self.x + self.ball_x - 5, self.y + self.ball_y - 5), size=(10, 10))

    def get_scaled_hole_pos(self, hole):
        phx, phy = hole.get("pos_hint", (0.5, 0.5))
        px = self.x + phx * max(0, self.width)
        py = self.y + phy * max(0, self.height)
        return px, py

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

    def replace_ball(self):
        self.ball_placed = False
        self.ball_x = -1000
        self.ball_y = -1000
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

    # Ball placement with small delay
    def on_touch_down(self, touch):
        if not self._accept_touches or not (self.mode_selected and self.mode == "Normal" and self.game_started):
            return False
        if not self.collide_point(*touch.pos):
            return False
        if self.ball_placed:
            return True
        local_x = touch.x - self.x
        local_y = touch.y - self.y
        Clock.schedule_once(lambda dt: self._place_ball(local_x, local_y), 0.1)
        return True

    def _place_ball(self, local_x, local_y):
        if self.ball_placed:
            return
        self.ball_x = local_x
        self.ball_y = local_y
        self.ball_placed = True
        # compute points for each hole
        max_dist = math.hypot(max(1, self.width), max(1, self.height))
        for i, hole in enumerate(self.holes):
            hx, hy = self.get_scaled_hole_pos(hole)
            dist = math.hypot(hx - self.x - local_x, hy - self.y - local_y)
            pts = int(round(MIN_READING + (dist / max_dist) * (MAX_READING - MIN_READING)))
            pts = max(MIN_READING, min(MAX_READING, pts))
            self.holes[i]["last_points"] = pts
            self.live_points_by_hole[hole["id"]] = pts
        # award score to player
        if self.current_player:
            self.player_scores.setdefault(self.current_player, []).append(MAX_READING)
        self.update_canvas()

    # Handle serial BT event
    def handle_hole_event(self, hole_id):
        hole = next((h for h in self.holes if h["id"] == hole_id), None)
        if not hole:
            return
        hx, hy = self.get_scaled_hole_pos(hole)
        local_x = hx - self.x
        local_y = hy - self.y
        self.ball_x = local_x
        self.ball_y = local_y
        self.ball_placed = True
        if self.current_player:
            self.player_scores.setdefault(self.current_player, []).append(MAX_READING)
        Clock.schedule_once(lambda dt: self.next_player(), 1.0)
        self.update_canvas()

# -----------------------
# Root and App
# -----------------------
class RootWidget(BoxLayout):
    pass

class MiniGolfApp(App):
    def build(self):
        root = RootWidget()
        try:
            self.green = root.ids.get("golf") or root.children[0]
        except Exception:
            self.green = None
        return root

    def on_start(self):
        if self.green:
            self.green.register_players(2)
            self.green.start_game()
        start_bt_threads(self.green)

# -----------------------
# Serial Bluetooth threads
# -----------------------
def serial_bt_thread(hole_id, port, green: GolfGreen):
    """Listen to a serial port for hole events."""
    while True:
        try:
            ser = serial.Serial(port, SERIAL_BAUD, timeout=1)
            print(f"[BT] 🔍 Scanning for HOLE_{hole_id} on {port}...")
            while True:
                line = ser.readline().decode(errors="ignore").strip()
                if line.startswith(f"HOLE:{hole_id}:1"):
                    print(f"[BT][HOLE_{hole_id}] {line}")
                    bt_event_queue.put(hole_id)
        except serial.SerialException:
            print(f"[BT] ❌ HOLE_{hole_id} not found; retrying in 5s")
            time.sleep(5)

def process_bt_queue(dt):
    app = App.get_running_app()
    while not bt_event_queue.empty():
        hid = bt_event_queue.get_nowait()
        Clock.schedule_once(lambda dt, hid=hid: app.green.handle_hole_event(hid), 0)

def start_bt_threads(green: GolfGreen):
    for hole_id, port in SERIAL_PORTS.items():
        t = threading.Thread(target=serial_bt_thread, args=(hole_id, port, green), daemon=True)
        t.start()
    Clock.schedule_interval(process_bt_queue, 0.1)

# -----------------------
if __name__ == "__main__":
    MiniGolfApp().run()
