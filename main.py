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
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.graphics import Color, Ellipse, Rectangle
from kivy.lang import Builder

# Attempt to import Classic Bluetooth
try:
    import bluetooth
except ImportError:
    bluetooth = None

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
BALL_RADIUS = 5

HOLE_NAME_PREFIXES = {1: "HOLE_1", 2: "HOLE_2", 3: "HOLE_3", 4: "HOLE_4", 5: "HOLE_5"}
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
            # Draw holes
            for hole in self.holes:
                hx, hy = self.get_scaled_hole_pos(hole)
                Color(1, 1, 1, 1)
                Ellipse(pos=(hx - hole["radius"], hy - hole["radius"]),
                        size=(hole["radius"]*2, hole["radius"]*2))
            # Draw ball
            if self.ball_placed:
                Color(1, 1, 1, 1)
                Ellipse(pos=(self.x + self.ball_x - BALL_RADIUS, self.y + self.ball_y - BALL_RADIUS),
                        size=(BALL_RADIUS*2, BALL_RADIUS*2))

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

    # Touch placement with delay
    def on_touch_down(self, touch):
        if not self._accept_touches:
            return True
        if not (self.mode_selected and self.mode == "Normal" and self.game_started):
            return False
        if not self.collide_point(*touch.pos):
            return False
        if self.ball_placed:
            return True
        self._touch_x = touch.x - self.x
        self._touch_y = touch.y - self.y
        Clock.schedule_once(self._place_ball, 0.3)
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

    # Bluetooth hole event
    def handle_hole_event(self, hole_id, scored=True):
        hole = next((h for h in self.holes if h["id"] == hole_id), None)
        if not hole:
            print("[BT] ❌ Unknown hole id", hole_id)
            return

        hx, hy = self.get_scaled_hole_pos(hole)
        self.ball_x = hx - self.x
        self.ball_y = hy - self.y
        self.ball_placed = True

        if self.current_player and scored:
            self.player_scores.setdefault(self.current_player, []).append(MAX_READING)
            print(f"[BT][HOLE_{hole_id}] 🏆 {self.current_player} scored {MAX_READING} at hole {hole_id}")

        Clock.schedule_once(lambda dt: self._next_player_bt(hole_id, scored), 1.0)
        self.update_canvas()

    def _next_player_bt(self, hole_id, scored):
        self.next_player()
        print(f"➡️ Next: {self.current_player} (Round {self.current_round})")

# -----------------------
# App and KV
# -----------------------
KV = """
<RootWidget>:
    orientation: "horizontal"
    padding: 6
    spacing: 6

    FloatLayout:
        size_hint_x: 0.75
        canvas.before:
            Color:
                rgba: 0,0,0,1
            Rectangle:
                pos: self.pos
                size: self.size

        GolfGreen:
            id: golf
            size: self.size
            pos: self.pos

        # Hole labels
        Label:
            text: "H1: " + (str(golf.holes[0].get('last_points')) if golf.holes[0].get('last_points') is not None else "-")
            size_hint: None, None
            size: 100, 24
            pos: (golf.get_scaled_hole_pos(golf.holes[0])[0] - self.width/2, golf.get_scaled_hole_pos(golf.holes[0])[1] + 12)
        Label:
            text: "H2: " + (str(golf.holes[1].get('last_points')) if golf.holes[1].get('last_points') is not None else "-")
            size_hint: None, None
            size: 100, 24
            pos: (golf.get_scaled_hole_pos(golf.holes[1])[0] - self.width/2, golf.get_scaled_hole_pos(golf.holes[1])[1] + 12)
        Label:
            text: "H3: " + (str(golf.holes[2].get('last_points')) if golf.holes[2].get('last_points') is not None else "-")
            size_hint: None, None
            size: 100, 24
            pos: (golf.get_scaled_hole_pos(golf.holes[2])[0] - self.width/2, golf.get_scaled_hole_pos(golf.holes[2])[1] + 12)
        Label:
            text: "H4: " + (str(golf.holes[3].get('last_points')) if golf.holes[3].get('last_points') is not None else "-")
            size_hint: None, None
            size: 100, 24
            pos: (golf.get_scaled_hole_pos(golf.holes[3])[0] - self.width/2, golf.get_scaled_hole_pos(golf.holes[3])[1] + 12)
        Label:
            text: "H5: " + (str(golf.holes[4].get('last_points')) if golf.holes[4].get('last_points') is not None else "-")
            size_hint: None, None
            size: 100, 24
            pos: (golf.get_scaled_hole_pos(golf.holes[4])[0] - self.width/2, golf.get_scaled_hole_pos(golf.holes[4])[1] + 12)

    BoxLayout:
        id: side_panel
        orientation: "vertical"
        size_hint_x: 0.25
        spacing: 10
        padding: 10
        canvas.before:
            Color:
                rgba: 0.2, 0.2, 0.2, 1
            Rectangle:
                pos: self.pos
                size: self.size

        BoxLayout:
            size_hint_y: None
            height: 40
            spacing: 6
            Label:
                text: "Current Player: " + (golf.current_player if golf.current_player else "None")

        BoxLayout:
            orientation: "vertical"
            spacing: 5
            size_hint_y: None
            height: 200
            Button:
                text: "1 Player"
                on_release: golf.register_players(1)
            Button:
                text: "2 Players"
                on_release: golf.register_players(2)
            Button:
                text: "3 Players"
                on_release: golf.register_players(3)
            Button:
                text: "Start Game"
                on_release: golf.start_game()
            Button:
                text: "Next Player"
                on_release: golf.next_player()
            Button:
                text: "Clear Scores"
                on_release: golf.clear_scores()
"""

Builder.load_string(KV)

class RootWidget(BoxLayout):
    pass

class MiniGolfApp(App):
    def build(self):
        root = RootWidget()
        self.green = root.ids.get("golf")
        return root

    def on_start(self):
        if self.green:
            self.green.register_players(2)
            self.green.start_game()
        start_bluetooth_threads(self.on_bt_event)

    def on_bt_event(self, hole_id, scored=True):
        if self.green:
            self.green.handle_hole_event(hole_id, scored)

# -----------------------
# Bluetooth Threads
# -----------------------
def bt_listen_thread(hole_id, name_prefix, callback):
    if not bluetooth:
        print(f"[BT] Bluetooth library not found, skipping {name_prefix}")
        return
    sock = None
    while True:
        try:
            print(f"[BT] 🔍 Scanning for {name_prefix}...")
            nearby = bluetooth.discover_devices(duration=6, lookup_names=True)
            target_addr = None
            for addr, name in nearby:
                if name and name_prefix in name:
                    target_addr = addr
                    break
            if not target_addr:
                print(f"[BT] ❌ {name_prefix} not found; retrying in {BT_RETRY_DELAY}s")
                time.sleep(BT_RETRY_DELAY)
                continue

            print(f"[BT] ✅ Found {name_prefix} at {target_addr}, connecting...")
            sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            sock.connect((target_addr, 1))
            sock.settimeout(1.0)
            buffer = b""
            print(f"[BT] 🔗 Connected to {name_prefix} ({target_addr})")

            while True:
                data = sock.recv(1024)
                if not data:
                    raise IOError("remote closed")
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    s = line.decode(errors="ignore").strip()
                    if s.startswith("HOLE:"):
                        parts = s.split(":")
                        try:
                            hid = int(parts[1])
                            scored = parts[2].startswith("1")
                            bt_event_queue.put((hid, scored))
                        except Exception:
                            pass
        except Exception as e:
            print(f"[BT] ⚠️ Error: {e}; reconnecting in {BT_RETRY_DELAY}s")
        finally:
            try: sock.close()
            except Exception: pass
            time.sleep(BT_RETRY_DELAY)

def start_bluetooth_threads(main_thread_callback):
    for hole_id, prefix in HOLE_NAME_PREFIXES.items():
        t = threading.Thread(target=bt_listen_thread, args=(hole_id, prefix, main_thread_callback), daemon=True)
        t.start()
    Clock.schedule_interval(process_bt_queue, 0.1)

def process_bt_queue(dt):
    app = App.get_running_app()
    while not bt_event_queue.empty():
        try:
            hole_id, scored = bt_event_queue.get_nowait()
            Clock.schedule_once(lambda dt, hid=hole_id, s=scored: app.on_bt_event(hid, s), 0)
        except Exception:
            pass

# -----------------------
if __name__ == "__main__":
    MiniGolfApp().run()
