# minigolf_with_bt.py
import math
import traceback
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
    mode = StringProperty("")          # "Normal" or "Practice"
    mode_selected = BooleanProperty(False)
    game_started = BooleanProperty(False)

    # startup safety for touchscreen ghost touches
    _accept_touches = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # redraw when size/pos change
        self.bind(size=self.update_canvas, pos=self.update_canvas)
        # enable touches after short delay to avoid ghost touch on Pi
        Clock.schedule_once(self._enable_touches, 0.5)
        # initial draw
        Clock.schedule_once(lambda dt: self.update_canvas(), 0)

    def _enable_touches(self, dt):
        self._accept_touches = True

    def update_canvas(self, *args):
        """Draw holes and ball on canvas.after so they appear above background."""
        self.canvas.after.clear()
        with self.canvas.after:
            # draw holes as white circles (same radius as before)
            for hole in self.holes:
                hx, hy = self.get_scaled_hole_pos(hole)
                Color(1, 1, 1, 1)
                Ellipse(pos=(hx - hole["radius"], hy - hole["radius"]),
                        size=(hole["radius"] * 2, hole["radius"] * 2))
            # draw ball as white (as requested). stays until next_player()
            if self.ball_placed:
                Color(1, 1, 1, 1)
                # ball is drawn centered at ball_x/ball_y with size 20x20
                Ellipse(pos=(self.x + self.ball_x - 10, self.y + self.ball_y - 10), size=(10, 10))

    # helper to compute total score for display
    def get_player_score(self, name):
        scores = self.player_scores.get(name, [])
        return sum(scores) if scores else 0

    # register players 1-3, reset score lists
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
        # Check if we need to advance to the next round
        if self.current_player_index >= len(self.players):
            self.current_player_index = 0
            self.current_round += 1
            if self.current_round > MAX_ROUNDS:
                print("Reached max rounds")
                return  # Optionally end the game here
            # Clear ball only at the start of a new round
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

    # touch placement left unchanged (manual placement)
    def on_touch_down(self, touch):
        # block early ghost touches
        if not self._accept_touches:
            print("Ignoring early touch (startup)")
            return True
        # only allow placement in Normal mode after game started
        if not (self.mode_selected and self.mode == "Normal" and self.game_started):
            return False
        # prevent touches on side panel from placing the ball
        root = App.get_running_app().root
        side = root.ids.get("side_panel", None)
        if side and side.collide_point(*touch.pos):
            return False
        # ignore touches outside the green
        if not self.collide_point(*touch.pos):
            return False
        # if ball already placed for this round, do not allow another placement
        if self.ball_placed:
            print("Ball already placed this round; ignore additional touches.")
            return True
        # schedule placement (short delay helps Pi touch timing)
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
        # compute points relative to holes and update last_points
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
        # determine hit and update current player's score
        nearest = min(results, key=lambda t: t[1]) if results else None
        hit = nearest and nearest[1] == 0
        if self.current_player:
            score = MAX_READING if hit else 0
            self.player_scores.setdefault(self.current_player, []).append(score)
        # set ball position (local coords) and lock it for the round
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

    # --- new: handle hole event coming from ESP32 via BT
    def handle_hole_event(self, hole_id):
        """
        Called from main thread when BT reports HOLE:<hole_id>:1.
        Behavior:
         - place the ball at hole center visually
         - award points to current player (MAX_READING)
         - advance to the next player
        """
        # find hole center
        hole = next((h for h in self.holes if h["id"] == hole_id), None)
        if not hole:
            print("Unknown hole id", hole_id)
            return

        hx, hy = self.get_scaled_hole_pos(hole)
        # convert to local coordinates
        local_x = hx - self.x
        local_y = hy - self.y

        # place ball visually and lock
        self.ball_x = local_x
        self.ball_y = local_y
        self.ball_placed = True

        # award points to current player
        if self.current_player:
            self.player_scores.setdefault(self.current_player, []).append(MAX_READING)
            print(f"Awarded {MAX_READING} to {self.current_player} for hole {hole_id}")

        # advance to next player after a short delay (so user can see)
        Clock.schedule_once(lambda dt: self.next_player(), 1.0)

        # redraw
        self.update_canvas()


class RootWidget(BoxLayout):
    pass


class MiniGolfApp(App):
    def build(self):
        root = RootWidget()
        # get the golf green widget (assumes it's the id 'golfgreen' in your kv or the first child)
        try:
            self.green = root.ids.get("golfgreen") or root.children[0]
        except Exception:
            self.green = None
        return root

    def on_start(self):
        # register two players as an example and start the game
        if self.green:
            self.green.register_players(2)
            self.green.start_game()
        # start Bluetooth listeners in background threads
        start_bluetooth_threads(self.on_bt_event)

    def on_bt_event(self, hole_id):
        """
        Called in the main thread via Clock when a BT event arrives.
        We forward it to the golf green to handle awarding points + visuals.
        """
        if self.green:
            self.green.handle_hole_event(hole_id)


# -----------------------
# Bluetooth background code (Classic RFCOMM via pybluez)
# -----------------------
def bt_listen_thread(hole_id, name_prefix, callback):
    """
    Background thread: finds device by name prefix, connects via RFCOMM,
    listens for lines, and pushes events into the Qt/Kivy main thread callback.
    Reconnects on failure.
    """
    sock = None
    while True:
        try:
            print(f"[BT] Scanning for devices containing '{name_prefix}' ...")
            nearby = bluetooth.discover_devices(duration=6, lookup_names=True)
            target_addr = None
            for addr, name in nearby:
                if name and name_prefix in name:
                    target_addr = addr
                    break
            if not target_addr:
                print(f"[BT] {name_prefix} not found; retrying in {BT_RETRY_DELAY}s")
                time.sleep(BT_RETRY_DELAY)
                continue

            print(f"[BT] Found {name_prefix} at {target_addr}, connecting...")
            sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            sock.connect((target_addr, 1))
            sock.settimeout(1.0)
            print(f"[BT] Connected to {name_prefix} ({target_addr})")

            buffer = b""
            while True:
                try:
                    data = sock.recv(1024)
                    if not data:
                        # connection closed
                        raise IOError("remote closed")
                    buffer += data
                    # process lines
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        s = line.decode(errors="ignore").strip()
                        if s:
                            print(f"[BT][{name_prefix}] {s}")
                            # expected format: HOLE:<id>:1
                            parts = s.split(":")
                            if len(parts) >= 3 and parts[0] == "HOLE":
                                try:
                                    hid = int(parts[1])
                                    if parts[2].startswith("1"):
                                        # schedule callback on Kivy main thread
                                        bt_event_queue.put(hid)
                                except ValueError:
                                    pass
                except bluetooth.btcommon.BluetoothError as be:
                    print(f"[BT] Bluetooth error: {be}; reconnecting")
                    break
                except IOError:
                    print("[BT] Connection lost; reconnecting")
                    break
        except Exception as e:
            print("[BT] Exception in BT thread:", e)
        finally:
            try:
                if sock:
                    sock.close()
            except Exception:
                pass
            time.sleep(BT_RETRY_DELAY)


def start_bluetooth_threads(main_thread_callback):
    """
    Spawn one thread per hole prefix to connect & listen.
    Also schedule a Kivy Clock poller to deliver queue events to the app.
    """
    for hole_id, prefix in HOLE_NAME_PREFIXES.items():
        t = threading.Thread(target=bt_listen_thread, args=(hole_id, prefix, main_thread_callback), daemon=True)
        t.start()
    # schedule the queue processor on Kivy main loop
    Clock.schedule_interval(process_bt_queue, 0.1)


def process_bt_queue(dt):
    """
    Called on Kivy main thread periodically. Pull events from bt_event_queue
    and call the app's event handler.
    """
    app = App.get_running_app()
    while not bt_event_queue.empty():
        try:
            hole_id = bt_event_queue.get_nowait()
            # safe call into app
            Clock.schedule_once(lambda dt, hid=hole_id: app.on_bt_event(hid), 0)
        except Exception as e:
            print("Error processing BT queue:", e)


if __name__ == "__main__":
    MiniGolfApp().run()
