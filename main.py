#!/usr/bin/env python3
import threading
import time
import subprocess
import serial
import shutil
from queue import Queue

from kivy.app import App
from kivy.clock import Clock
from kivy.properties import ListProperty, NumericProperty, StringProperty, DictProperty, BooleanProperty
from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout
from kivy.graphics import Color, Ellipse

# -----------------------
# Config (same as before)
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

HOLE_NAME_PREFIXES = {
    1: "HOLE_1",
    2: "HOLE_2",
    3: "HOLE_3",
    4: "HOLE_4",
    5: "HOLE_5",
}

BT_RETRY_DELAY = 5
bt_event_queue = Queue()

def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip()
    except Exception as e:
        print("⚠️", e)
        return ""

# (bt_auto_thread, GolfGreen, RootWidget, process_bt_queue, start_bt_threads,
#  open_bt_terminal implementations remain unchanged from previous working version)
# For brevity paste your existing implementations here — do NOT call Builder.load_file anywhere.

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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(size=self.update_canvas,
                  pos=self.update_canvas,
                  ball_placed=self.update_canvas,
                  ball_x=self.update_canvas,
                  ball_y=self.update_canvas)
        Clock.schedule_once(lambda dt: self.update_canvas(), 0)

    def update_canvas(self, *args):
        self.canvas.after.clear()
        with self.canvas.after:
            for hole in self.holes:
                hx, hy = self.get_scaled_hole_pos(hole)
                Color(0, 0, 0, 1)
                Ellipse(pos=(hx - hole["radius"], hy - hole["radius"]), size=(hole["radius"]*2, hole["radius"]*2))
            if self.ball_placed:
                Color(1, 0, 0, 1)
                Ellipse(pos=(self.x + self.ball_x - 6, self.y + self.ball_y - 6), size=(12, 12))

    def get_scaled_hole_pos(self, hole):
        phx, phy = hole.get("pos_hint", (0.5, 0.5))
        px = self.x + phx * self.width
        py = self.y + phy * self.height
        return px, py

    def register_players(self, count=2):
        self.players = [f"Player {i+1}" for i in range(count)]
        self.player_scores = {p: [] for p in self.players}
        self.current_player_index = 0
        self.current_round = 1
        self.current_player = self.players[0]
        self.game_started = True
        print("Players registered:", self.players)

    def get_player_score(self, player):
        scores = self.player_scores.get(player, [])
        return sum(scores) if scores else 0

    def next_player(self):
        if not self.players:
            return
        self.current_player_index += 1
        if self.current_player_index >= len(self.players):
            self.current_player_index = 0
            self.current_round += 1
        self.current_player = self.players[self.current_player_index]
        print(f"Next: {self.current_player} (Round {self.current_round})")

    def handle_hole_event(self, hole_id):
        hole = next((h for h in self.holes if h["id"] == hole_id), None)
        if not hole:
            print(f"Unknown hole {hole_id}")
            return
        hx, hy = self.get_scaled_hole_pos(hole)
        Clock.schedule_once(lambda dt: self.place_ball(hx, hy, hole_id), 0.25)

    def place_ball(self, hx, hy, hole_id):
        self.ball_x = hx - self.x
        self.ball_y = hy - self.y
        self.ball_placed = True
        if self.current_player:
            self.player_scores.setdefault(self.current_player, []).append(MAX_READING)
            print(f"{self.current_player} scored {MAX_READING} at hole {hole_id}")
        Clock.schedule_once(lambda dt: self.next_player(), 1)
        Clock.schedule_once(lambda dt: self.update_canvas(), 0)

    def clear_scores(self):
        self.player_scores = {p: [] for p in self.players}
        self.ball_placed = False
        self.ball_x, self.ball_y = -1000, -1000
        Clock.schedule_once(lambda dt: self.update_canvas(), 0)

    def start_game(self):
        self.game_started = True
        self.current_round = 1
        if self.players:
            self.current_player_index = 0
            self.current_player = self.players[0]

class RootWidget(BoxLayout):
    pass

# Implement bt_auto_thread, process_bt_queue, start_bt_threads, open_bt_terminal here
# (paste from your working version; keep exactly one place where you open terminals or start threads)

class MiniGolfApp(App):
    def build(self):
        # Do NOT call Builder.load_file here; let Kivy auto-load minigolf.kv
        # and return a Python-created root instance.
        return RootWidget()

    def on_start(self):
        # This requires that minigolf.kv defines ids.golf under RootWidget
        self.green = self.root.ids.golf
        self.green.register_players(2)
        Clock.schedule_interval(process_bt_queue, 0.1)
        start_bt_threads()
        open_bt_terminal()

if __name__ == "__main__":
    MiniGolfApp().run()