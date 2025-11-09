# minigolf_ble.py
import math
import asyncio
from queue import Queue
from threading import Thread

from kivy.app import App
from kivy.clock import Clock
from kivy.properties import ListProperty, NumericProperty, StringProperty, DictProperty, BooleanProperty
from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout
from kivy.graphics import Color, Ellipse

from bleak import BleakScanner, BleakClient

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

MAX_PLAYERS = 3
MAX_ROUNDS = 10
MAX_READING = 10

# Names or partial names of BLE devices for each hole
HOLE_NAME_PREFIXES = {
    1: "HOLE_1",
    2: "HOLE_2",
    3: "HOLE_3",
    4: "HOLE_4",
    5: "HOLE_5",
}

# BLE event queue
ble_event_queue = Queue()


# -----------------------
# Kivy Golf Widget
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
            for hole in self.holes:
                hx, hy = self.get_scaled_hole_pos(hole)
                Color(1, 1, 1, 1)
                Ellipse(pos=(hx - hole["radius"], hy - hole["radius"]),
                        size=(hole["radius"] * 2, hole["radius"] * 2))
            if self.ball_placed:
                Color(1, 1, 1, 1)
                Ellipse(pos=(self.x + self.ball_x - 5, self.y + self.ball_y - 5), size=(10, 10))  # smaller ball

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
            print("No players")
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
                print("Game over")
                return
            self.ball_placed = False
            self.ball_x = -1000
            self.ball_y = -1000
        self.current_player = self.players[self.current_player_index]
        self.update_canvas()
        print(f"Next player: {self.current_player} (Round {self.current_round})")

    def get_scaled_hole_pos(self, hole):
        phx, phy = hole.get("pos_hint", (0.5, 0.5))
        px = self.x + phx * max(0, self.width)
        py = self.y + phy * max(0, self.height)
        return px, py

    def get_player_score(self, name):
        return sum(self.player_scores.get(name, []))

    # BLE event handler
    def handle_hole_event(self, hole_id):
        hole = next((h for h in self.holes if h["id"] == hole_id), None)
        if not hole:
            print("Unknown hole id", hole_id)
            return
        hx, hy = self.get_scaled_hole_pos(hole)
        local_x = hx - self.x
        local_y = hy - self.y
        self.ball_x = local_x
        self.ball_y = local_y
        self.ball_placed = True
        if self.current_player:
            self.player_scores.setdefault(self.current_player, []).append(MAX_READING)
            print(f"🏆 {self.current_player} scored {MAX_READING} at hole {hole_id}")
        Clock.schedule_once(lambda dt: self.next_player(), 1.0)
        self.update_canvas()


# -----------------------
# Kivy App
# -----------------------
class RootWidget(BoxLayout):
    pass


class MiniGolfApp(App):
    def build(self):
        root = RootWidget()
        self.green = root.ids.get("golf") or root.children[0]
        return root

    def on_start(self):
        if self.green:
            self.green.register_players(2)
            self.green.start_game()
        # start BLE scanning in background
        Thread(target=self.ble_loop_thread, daemon=True).start()
        Clock.schedule_interval(self.process_ble_queue, 0.1)

    def process_ble_queue(self, dt):
        while not ble_event_queue.empty():
            hole_id = ble_event_queue.get_nowait()
            if self.green:
                self.green.handle_hole_event(hole_id)

    def ble_loop_thread(self):
        asyncio.run(self.ble_loop())

    async def ble_loop(self):
        while True:
            devices = await BleakScanner.discover()
            for hole_id, prefix in HOLE_NAME_PREFIXES.items():
                for d in devices:
                    if d.name and prefix in d.name:
                        print(f"[BLE] Found {prefix}: {d.address}")
                        # simulate hole hit for testing
                        ble_event_queue.put(hole_id)
            await asyncio.sleep(5)


if __name__ == "__main__":
    MiniGolfApp().run()
