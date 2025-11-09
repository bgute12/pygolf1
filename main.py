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

# Serial communication
import serial

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

# Map hole IDs to serial ports (replace with your actual /dev/rfcommX ports)
HOLE_SERIAL_PORTS = {
    1: "/dev/rfcomm1",
    2: "/dev/rfcomm2",
    3: "/dev/rfcomm3",
    4: "/dev/rfcomm4",
    5: "/dev/rfcomm5",
}

SERIAL_BAUDRATE = 115200
SERIAL_RETRY_DELAY = 5  # seconds

# Queue for passing events from BT threads to Kivy main thread
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
    mode = StringProperty("")  # "Normal" or "Practice"
    mode_selected = BooleanProperty(False)
    game_started = BooleanProperty(False)

    _accept_touches = False  # startup safety

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
        print("Registered players:", self.players)

    def start_game(self):
        if not self.players:
            print("No players, cannot start")
            return
        self.game_started = True
        self.ball_placed = False
        self.current_player_index = 0
        self.current_player = self.players[self.current_player_index]
        self.update_canvas()
        print("Game started. Current player:", self.current_player)

    def replace_ball(self):
        if not self.game_started:
            print("Replace Ball blocked: game not started")
            return
        if self.current_player_index != 0:
            print("Replace Ball blocked: not first player of the round")
            return
        self.ball_x = -1000
        self.ball_y = -1000
        self.ball_placed = False
        self.update_canvas()
        print("Replace Ball: ready for re-placement")

    def next_player(self):
        if not self.players:
            return
        self.current_player_index += 1
        if self.current_player_index >= len(self.players):
            self.current_player_index = 0
            self.current_round += 1
            if self.current_round > MAX_ROUNDS:
                print("Reached max rounds")
                return
            self.ball_placed = False
            self.ball_x = -1000
            self.ball_y = -1000
        self.current_player = self.players[self.current_player_index]
        self.update_canvas()
        print(f"Next player: {self.current_player} (Round {self.current_round})")

    def clear_scores(self):
        self.player_scores = {p: [] for p in self.players}
        self.update_canvas()

    def get_scaled_hole_pos(self, hole):
        phx, phy = hole.get("pos_hint", (0.5, 0.5))
        px = self.x + phx * max(0, self.width)
        py = self.y + phy * max(0, self.height)
        return px, py

    def on_touch_down(self, touch):
        if not self._accept_touches:
            return True
        if not (self.mode_selected and self.mode == "Normal" and self.game_started):
            return False
        root = App.get_running_app().root
        side = root.ids.get("side_panel", None)
        if side and side.collide_point(*touch.pos):
            return False
        if not self.collide_point(*touch.pos):
            return False
        if self.ball_placed:
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
        max_dist = math.hypot(max(1, self.width), max(1, self.height))
        results = []
        for i, hole in enumerate(self.holes):
            hx, hy = self.get_scaled_hole_pos(hole)
            local_hx = hx - self.x
            local_hy = hy - self.y
            dist = math.hypot(local_hx - local_x, local_hy - local_y)
            pts = self.distance_to_reading(dist, max_dist)
            new_h = hole.copy()
            new_h["last_points"] = pts
            self.holes[i] = new_h
            results.append((new_h["id"], pts))
            self.live_points_by_hole[new_h["id"]] = pts
        nearest = min(results, key=lambda t: t[1]) if results else None
        hit = nearest and nearest[1] == 0
        if self.current_player:
            score = MAX_READING if hit else 0
            self.player_scores.setdefault(self.current_player, []).append(score)
        self.ball_x = local_x
        self.ball_y = local_y
        self.ball_placed = True
        self.update_canvas()
        print(f"Placed ball for {self.current_player} at ({local_x:.1f},{local_y:.1f}), nearest={nearest}")

    def distance_to_reading(self, dist, max_dist):
        norm = 0.0 if (max_dist is None or max_dist <= 0) else min(1.0, dist / max_dist)
        cont = MIN_READING + norm * (MAX_READING - MIN_READING)
        pts = int(round(cont))
        return max(MIN_READING, min(MAX_READING, pts))

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
            print(f"Awarded {MAX_READING} to {self.current_player} for hole {hole_id}")
        Clock.schedule_once(lambda dt: self.next_player(), 1.0)
        self.update_canvas()


class RootWidget(BoxLayout):
    pass


class MiniGolfApp(App):
    def build(self):
        root = RootWidget()
        try:
            self.green = root.ids.get("golfgreen") or root.children[0]
        except Exception:
            self.green = None
        return root

    def on_start(self):
        if self.green:
            self.green.register_players(2)
            self.green.start_game()
        start_serial_threads()

    def on_bt_event(self, hole_id):
        if self.green:
            self.green.handle_hole_event(hole_id)


# -----------------------
# Serial background threads
# -----------------------
def serial_listen_thread(hole_id, port):
    while True:
        try:
            print(f"[Serial][Hole {hole_id}] Opening port {port} ...")
            with serial.Serial(port, SERIAL_BAUDRATE, timeout=1) as ser:
                print(f"[Serial][Hole {hole_id}] Connected.")
                while True:
                    line = ser.readline().decode(errors="ignore").strip()
                    if line:
                        parts = line.split(":")
                        if len(parts) >= 3 and parts[0] == "HOLE":
                            try:
                                hid = int(parts[1])
                                if parts[2].startswith("1"):
                                    bt_event_queue.put(hid)
                            except ValueError:
                                pass
        except Exception as e:
            print(f"[Serial][Hole {hole_id}] Error: {e}; retrying in {SERIAL_RETRY_DELAY}s")
            time.sleep(SERIAL_RETRY_DELAY)


def start_serial_threads():
    for hole_id, port in HOLE_SERIAL_PORTS.items():
        t = threading.Thread(target=serial_listen_thread, args=(hole_id, port), daemon=True)
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
