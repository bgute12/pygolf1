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
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.graphics import Color, Ellipse, Rectangle

# Classic Bluetooth library (pybluez)
import bluetooth

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

# Names to search for (partial match). ESP32 devices should advertise names containing these.
HOLE_NAME_PREFIXES = {
    1: "HOLE_1",
    2: "HOLE_2",
    3: "HOLE_3",
    4: "HOLE_4",
    5: "HOLE_5",
}

# Bluetooth reconnect delay (seconds)
BT_RETRY_DELAY = 5

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
    ball_x = NumericProperty(-1000)   # coordinates are local to widget (not absolute)
    ball_y = NumericProperty(-1000)
    holes = ListProperty(HOLES.copy())
    ball_placed = BooleanProperty(False)
    mode = StringProperty("Normal")          # "Normal" or "Practice"
    mode_selected = BooleanProperty(True)
    game_started = BooleanProperty(False)

    # startup safety for touchscreen ghost touches
    _accept_touches = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(size=self.update_canvas, pos=self.update_canvas)
        Clock.schedule_once(self._enable_touches, 0.5)
        Clock.schedule_once(lambda dt: self.update_canvas(), 0)

    def _enable_touches(self, dt):
        self._accept_touches = True

    def update_canvas(self, *args):
        """Draw background, holes, and ball."""
        self.canvas.before.clear()
        self.canvas.after.clear()

        # Green background
        with self.canvas.before:
            Color(0, 0.6, 0, 1)  # green
            Rectangle(pos=self.pos, size=self.size)

        # Holes and ball
        with self.canvas.after:
            for hole in self.holes:
                hx, hy = self.get_scaled_hole_pos(hole)
                Color(1, 1, 1, 1)
                Ellipse(pos=(hx - hole["radius"], hy - hole["radius"]),
                        size=(hole["radius"] * 2, hole["radius"] * 2))
            if self.ball_placed:
                Color(1, 1, 1, 1)
                Ellipse(pos=(self.x + self.ball_x - 10, self.y + self.ball_y - 10), size=(20, 20))

    # --- player management ---
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

    def replace_ball(self):
        if not self.game_started or self.current_player_index != 0:
            return
        self.ball_x = -1000
        self.ball_y = -1000
        self.ball_placed = False
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

    # --- touch placement ---
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
            dist = math.hypot(hx - self.x - local_x, hy - self.y - local_y)
            pts = int(round(MIN_READING + min(1, dist / max_dist) * (MAX_READING - MIN_READING)))
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

    # --- handle BT hole event ---
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


# -----------------------
# Root widget + side panel
# -----------------------
class RootWidget(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'horizontal'

        # Golf green area
        self.golfgreen = GolfGreen(size_hint=(0.75, 1))
        self.add_widget(self.golfgreen)

        # Side panel
        side_panel = BoxLayout(orientation='vertical', size_hint=(0.25, 1), spacing=10, padding=10)

        btn_next = Button(text="Next Player", size_hint_y=None, height=50)
        btn_next.bind(on_release=lambda x: self.golfgreen.next_player())
        side_panel.add_widget(btn_next)

        btn_replace = Button(text="Replace Ball", size_hint_y=None, height=50)
        btn_replace.bind(on_release=lambda x: self.golfgreen.replace_ball())
        side_panel.add_widget(btn_replace)

        btn_clear = Button(text="Clear Scores", size_hint_y=None, height=50)
        btn_clear.bind(on_release=lambda x: self.golfgreen.clear_scores())
        side_panel.add_widget(btn_clear)

        self.player_label = Label(text="", size_hint_y=None, height=50)
        side_panel.add_widget(self.player_label)

        self.add_widget(side_panel)
        Clock.schedule_interval(self.update_labels, 0.1)

    def update_labels(self, dt):
        if self.golfgreen.players:
            self.player_label.text = f"Current: {self.golfgreen.current_player}\nRound: {self.golfgreen.current_round}"


# -----------------------
# App
# -----------------------
class MiniGolfApp(App):
    def build(self):
        root = RootWidget()
        self.green = root.golfgreen
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
# Bluetooth threads
# -----------------------
def bt_listen_thread(hole_id, name_prefix, callback):
    sock = None
    while True:
        try:
            nearby = bluetooth.discover_devices(duration=6, lookup_names=True)
            target_addr = None
            for addr, name in nearby:
                if name and name_prefix in name:
                    target_addr = addr
                    break
            if not target_addr:
                time.sleep(BT_RETRY_DELAY)
                continue
            sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            sock.connect((target_addr, 1))
            sock.settimeout(1.0)
            buffer = b""
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
                        if len(parts) >= 3 and parts[2].startswith("1"):
                            try:
                                hid = int(parts[1])
                                bt_event_queue.put(hid)
                            except:
                                pass
        except:
            pass
        finally:
            try: sock.close()
            except: pass
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
            hole_id = bt_event_queue.get_nowait()
            Clock.schedule_once(lambda dt, hid=hole_id: app.on_bt_event(hid), 0)
        except:
            pass

if __name__ == "__main__":
    MiniGolfApp().run()
