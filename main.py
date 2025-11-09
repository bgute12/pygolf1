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
from kivy.uix.label import Label
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

HOLE_NAME_PREFIXES = {
    1: "HOLE_1",
    2: "HOLE_2",
    3: "HOLE_3",
    4: "HOLE_4",
    5: "HOLE_5",
}

BT_RETRY_DELAY = 5  # seconds
bt_event_queue = Queue()

def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip()
    except Exception as e:
        print("⚠️", e)
        return ""

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
                    parts = line.split()
                    if len(parts) >= 2:
                        addr = parts[1]
                        break
            if not addr:
                print(f"[BT] {name_prefix} not found; retrying in {BT_RETRY_DELAY}s")
                time.sleep(BT_RETRY_DELAY)
                continue
            print(f"[BT] Found {name_prefix} at {addr}")
            run_cmd(f"bluetoothctl pair {addr}")
            run_cmd(f"bluetoothctl trust {addr}")
            run_cmd(f"bluetoothctl connect {addr}")
            run_cmd(f"sudo rfcomm release {hole_id} || true")
            run_cmd(f"sudo rfcomm bind {hole_id} {addr} 1")
            print(f"[BT] Bound {addr} -> {port}")
            ser = None
            for _ in range(3):
                try:
                    ser = serial.Serial(port, 9600, timeout=1)
                    print(f"[BT] Listening on {port}")
                    break
                except Exception:
                    time.sleep(1)
            if not ser:
                print(f"[BT] Cannot open {port}, retrying...")
                time.sleep(BT_RETRY_DELAY)
                continue
            while True:
                data = ser.readline()
                if not data:
                    continue
                msg = data.decode(errors="ignore").strip()
                if msg:
                    print(f"[BT][{name_prefix}] {msg}")
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
# GolfGreen (one placement per round)
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
    game_started = BooleanProperty(False)

    MAX_SCORE_RADIUS = 200
    _pending_place_ev = None

    # Only one placement allowed per round
    placed_this_round = BooleanProperty(False)

    hole_points = DictProperty({})
    hole_labels = {}

    BALL_DISPLAY_SIZE = 6
    HOLE_COLOR = (1, 1, 1, 1)
    BALL_COLOR = (1, 1, 1, 1)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Clock.schedule_once(lambda dt: self._create_hole_labels(), 0)
        self.bind(size=self._update_everything, pos=self._update_everything,
                  ball_placed=self._update_everything, ball_x=self._update_everything, ball_y=self._update_everything)
        Clock.schedule_once(lambda dt: self.update_canvas(), 0)

    def _create_hole_labels(self):
        for lbl in self.hole_labels.values():
            try:
                self.remove_widget(lbl)
            except Exception:
                pass
        self.hole_labels = {}
        for hole in self.holes:
            lid = hole["id"]
            lbl = Label(text="", font_size="12sp", size_hint=(None, None))
            self.hole_labels[lid] = lbl
            self.add_widget(lbl)
        self._update_hole_labels()

    def _update_hole_labels(self):
        for hole in self.holes:
            hid = hole["id"]
            hx, hy = self.get_scaled_hole_pos(hole)
            lbl = self.hole_labels.get(hid)
            if not lbl:
                continue
            pts = self.hole_points.get(hid)
            lbl.text = f"{pts}" if pts is not None else ""
            w = 40; h = 18
            lbl.size = (w, h)
            lbl.pos = (hx - w / 2, hy + hole.get("radius", 8) + 6)

    def _update_everything(self, *args):
        self.update_canvas()
        self._update_hole_labels()

    def update_canvas(self, *args):
        self.canvas.after.clear()
        with self.canvas.after:
            for hole in self.holes:
                hx, hy = self.get_scaled_hole_pos(hole)
                Color(*self.HOLE_COLOR)
                r = hole.get("radius", 8)
                Ellipse(pos=(hx - r, hy - r), size=(r * 2, r * 2))
            if self.ball_placed:
                Color(*self.BALL_COLOR)
                size = self.BALL_DISPLAY_SIZE
                Ellipse(pos=(self.x + self.ball_x - size / 2, self.y + self.ball_y - size / 2), size=(size, size))

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
        self.placed_this_round = False
        print("Players registered:", self.players)

    def get_player_score(self, player):
        scores = self.player_scores.get(player, [])
        return sum(scores) if scores else 0

    def _advance_round_after_single_placement(self):
        # Immediately advance round. Reset placement flag so next round allows one placement.
        self.current_round += 1
        self.placed_this_round = False
        # Reset current player index to 0 (optional)
        self.current_player_index = 0
        self.current_player = self.players[0] if self.players else ""
        print(f"--- Advanced to round {self.current_round} ---")

    def handle_hole_event(self, hole_id):
        if self.placed_this_round:
            print("A placement has already occurred this round; ignoring.")
            return
        hole = next((h for h in self.holes if h["id"] == hole_id), None)
        if not hole:
            print(f"Unknown hole {hole_id}")
            return
        hx, hy = self.get_scaled_hole_pos(hole)
        self._schedule_place(hx, hy, hole_id)

    def _schedule_place(self, hx, hy, hole_id=None):
        if self._pending_place_ev is not None:
            try:
                Clock.unschedule(self._pending_place_ev)
            except Exception:
                pass
            self._pending_place_ev = None
        self._pending_place_ev = Clock.schedule_once(lambda dt: self._do_place(hx, hy, hole_id), 0.5)

    def _do_place(self, hx, hy, hole_id=None):
        self._pending_place_ev = None
        self.place_ball(hx, hy, hole_id)

    def place_ball(self, hx, hy, hole_id=None):
        if self.placed_this_round:
            print("Ignored placement; this round already had a placement.")
            return

        self.ball_x = hx - self.x
        self.ball_y = hy - self.y
        self.ball_placed = True

        nearest = None; nearest_d = None
        for hole in self.holes:
            phx, phy = self.get_scaled_hole_pos(hole)
            d = ((phx - hx) ** 2 + (phy - hy) ** 2) ** 0.5
            if nearest is None or d < nearest_d:
                nearest = hole; nearest_d = d

        if nearest is None:
            Clock.schedule_once(lambda dt: self.update_canvas(), 0)
            return

        target_hole = next((h for h in self.holes if h["id"] == hole_id), nearest)
        thx, thy = self.get_scaled_hole_pos(target_hole)
        dist = ((thx - hx) ** 2 + (thy - hy) ** 2) ** 0.5

        radius = target_hole.get("radius", 8)
        if dist <= radius:
            score = MAX_READING
        elif dist >= self.MAX_SCORE_RADIUS:
            score = MIN_READING
        else:
            frac = (dist - radius) / max(1, (self.MAX_SCORE_RADIUS - radius))
            score = int(round(MAX_READING - frac * (MAX_READING - MIN_READING)))
            score = max(MIN_READING, min(MAX_READING, score))

        # Attribute to current player
        if self.current_player:
            self.player_scores.setdefault(self.current_player, []).append(score)
            print(f"{self.current_player} scored {score} (dist={int(dist)} px) at hole {target_hole['id']}")

        # record last points for hole and update labels
        self.hole_points[target_hole["id"]] = score
        self._update_hole_labels()

        # mark placement happened and advance round shortly after
        self.placed_this_round = True
        Clock.schedule_once(lambda dt: self._advance_round_after_single_placement(), 0.1)
        Clock.schedule_once(lambda dt: self.update_canvas(), 0)

    def clear_scores(self):
        self.player_scores = {p: [] for p in self.players}
        self.hole_points = {}
        self.ball_placed = False
        self.ball_x, self.ball_y = -1000, -1000
        self.placed_this_round = False
        self._update_hole_labels()
        Clock.schedule_once(lambda dt: self.update_canvas(), 0)

    def start_game(self):
        self.game_started = True
        self.current_round = 1
        if self.players:
            self.current_player_index = 0
            self.current_player = self.players[0]
        self.placed_this_round = False

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        if self.placed_this_round:
            print("A placement has already been made this round.")
            return True
        tx, ty = touch.pos
        self._schedule_place(tx, ty)
        return True

# -----------------------
# Helpers and App
# -----------------------
def process_bt_queue(dt):
    app = App.get_running_app()
    while not bt_event_queue.empty():
        hid = bt_event_queue.get_nowait()
        Clock.schedule_once(lambda dt, hole=hid: app.green.handle_hole_event(hole), 0)

def start_bt_threads():
    for hid, prefix in HOLE_NAME_PREFIXES.items():
        threading.Thread(target=bt_auto_thread, args=(hid, prefix), daemon=True).start()

def open_bt_terminal():
    cmd_shell = "bluetoothctl"
    terminals = [
        ("x-terminal-emulator", ["-e", f"bash -c \"{cmd_shell}; exec bash\""]),
        ("gnome-terminal", ["--", "bash", "-c", f"{cmd_shell}; exec bash"]),
        ("konsole", ["-e", f"bash -c \"{cmd_shell}; exec bash\""]),
        ("xfce4-terminal", ["-e", f"bash -c \"{cmd_shell}; exec bash\""]),
        ("lxterminal", ["-e", f"bash -c \"{cmd_shell}; exec bash\""]),
        ("alacritty", ["-e", "bash", "-c", f"{cmd_shell}; exec bash"]),
        ("xterm", ["-e", f"bash -c \"{cmd_shell}; exec bash\""]),
    ]
    for term, args in terminals:
        path = shutil.which(term)
        if path:
            try:
                subprocess.Popen([path] + args)
                print(f"[BT] Opened bluetoothctl in {term}")
                return True
            except Exception as e:
                print(f"[BT] Failed to launch {term}: {e}")
    print("[BT] Could not find a terminal emulator. Run bluetoothctl manually.")
    return False

class RootWidget(BoxLayout):
    pass

class MiniGolfApp(App):
    def build(self):
        return RootWidget()

    def on_start(self):
        self.green = self.root.ids.golf
        self.green.register_players(2)
        Clock.schedule_interval(process_bt_queue, 0.1)
        start_bt_threads()
        # optional: open_bt_terminal()

if __name__ == "__main__":
    MiniGolfApp().run()