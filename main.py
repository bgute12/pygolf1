import math
from kivy.app import App
from kivy.clock import Clock
from kivy.properties import (
    ListProperty, NumericProperty, StringProperty, DictProperty, BooleanProperty
)
from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout
from kivy.graphics import Color, Ellipse

# Keep same hole definitions/positions as before
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

class GolfGreen(Widget):
    players = ListProperty([])
    current_player_index = NumericProperty(0)
    current_round = NumericProperty(1)
    current_player = StringProperty("")
    player_scores = DictProperty({})
    live_text = StringProperty("")
    live_points_by_hole = DictProperty({})
    ball_x = NumericProperty(-1000)   # local coords relative to widget
    ball_y = NumericProperty(-1000)
    holes = ListProperty(HOLES.copy())
    ball_placed = BooleanProperty(False)
    mode = StringProperty("")          # "Normal" or "Practice"
    mode_selected = BooleanProperty(False)
    game_started = BooleanProperty(False)

    # ball visual size
    ball_radius = NumericProperty(6)

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
            # draw holes as white circles
            for hole in self.holes:
                hx, hy = self.get_scaled_hole_pos(hole)
                Color(1, 1, 1, 1)
                Ellipse(pos=(hx - hole["radius"], hy - hole["radius"]),
                        size=(hole["radius"] * 2, hole["radius"] * 2))
            # draw ball as white if placed
            if self.ball_placed:
                Color(1, 1, 1, 1)
                Ellipse(
                    pos=(self.x + self.ball_x - self.ball_radius, self.y + self.ball_y - self.ball_radius),
                    size=(self.ball_radius * 2, self.ball_radius * 2)
                )

        # update hole label positions in parent (if present)
        try:
            root = App.get_running_app().root
            if root and hasattr(root, 'ids'):
                # update labels positions and texts if labels exist
                for i, hole in enumerate(self.holes, start=1):
                    hid = f"h{i}"
                    lbl = root.ids.get(hid)
                    if lbl:
                        hx, hy = self.get_scaled_hole_pos(hole)
                        # convert to parent coordinates (labels are direct children of FloatLayout)
                        lbl.pos = (hx - lbl.width / 2, hy + 12)
                        lp = hole.get("last_points")
                        lbl.text = f"H{i}: {lp if lp is not None else '-'}"
        except Exception:
            pass

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
        # clear hole last_points
        newholes = []
        for h in HOLES:
            nh = h.copy()
            nh["last_points"] = None
            newholes.append(nh)
        self.holes = newholes
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
        # ensure ball coords cleared so first player can place
        self.ball_x = -1000
        self.ball_y = -1000
        self.update_canvas()
        print("Game started. Current player:", self.current_player)

    def replace_ball(self):
        """
        Allowed only for the first player of each round (index 0).
        Can be called multiple times until the first player finishes placement.
        """
        if not self.game_started:
            print("Replace Ball blocked: game not started")
            return
        # only allow first player of current round to replace
        if self.current_player_index != 0:
            print("Replace Ball blocked: not first player of the round")
            return

        # Clear the stored ball so the first player can re-place (multiple times)
        self.ball_x = -1000
        self.ball_y = -1000
        self.ball_placed = False
        # clear hole last_points (so readings recompute on next placement)
        for i, hole in enumerate(self.holes):
            nh = hole.copy()
            nh["last_points"] = None
            self.holes[i] = nh
        self.live_points_by_hole.clear()
        self.update_canvas()
        print("Replace Ball: ready for re-placement by first player")

    def next_player(self):
        if not self.players:
            return

        # Advance to next player index
        self.current_player_index += 1

        # If we've cycled past last player, we start a new round
        if self.current_player_index >= len(self.players):
            self.current_player_index = 0
            self.current_round += 1
            if self.current_round > MAX_ROUNDS:
                print("Reached max rounds")
                # Optionally end game here; keep state as-is
            # At the start of a new round, clear ball so first player places again
            self.ball_placed = False
            self.ball_x = -1000
            self.ball_y = -1000
            # Also clear hole last_points for new round
            for i, hole in enumerate(self.holes):
                nh = hole.copy()
                nh["last_points"] = None
                self.holes[i] = nh
            self.live_points_by_hole.clear()

        self.current_player = self.players[self.current_player_index]
        # For players other than first in the current round, ball should remain where first placed it
        # (i.e., do NOT reset ball_placed here)
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

        # If ball already placed for this round, do not allow another placement by others
        # The first player is allowed to replace multiple times before the ball is 'committed'
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
        # avoid placing twice
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

        # determine hit (reading 0 = hit) and update current player's score
        nearest = min(results, key=lambda t: t[1]) if results else None
        hit = nearest and nearest[1] == 0
        if self.current_player:
            # store a single score for this player's turn: MAX_READING for hit else 0 (same as original behavior)
            score = MAX_READING if hit else 0
            self.player_scores.setdefault(self.current_player, []).append(score)

        # set ball position (local coords) and lock it for the round
        self.ball_x = local_x
        self.ball_y = local_y
        self.ball_placed = True
        # redraw visuals
        self.update_canvas()
        print(f"Placed ball for {self.current_player} at ({local_x:.1f},{local_y:.1f}), nearest={nearest}")

        # Optionally send readout over Bluetooth if implemented
        try:
            self.bluetooth_send({"event": "ball_placed", "player": self.current_player, "points_by_hole": self.live_points_by_hole})
        except Exception:
            pass

    def distance_to_reading(self, dist, max_dist):
        norm = 0.0 if (max_dist is None or max_dist <= 0) else min(1.0, dist / max_dist)
        cont = MIN_READING + norm * (MAX_READING - MIN_READING)
        pts = int(round(cont))
        return max(MIN_READING, min(MAX_READING, pts))

    # --- Bluetooth placeholder methods (non-blocking stubs you can implement) ---
    def bluetooth_send(self, payload):
        """
        Hook for sending payload via Bluetooth.
        Replace this stub with your actual bluetooth send code.
        """
        # Example: print("BT SEND:", payload)
        pass

    def bluetooth_receive(self, payload):
        """
        Hook that you can call when a Bluetooth message arrives.
        Implement parsing/handling as needed.
        """
        # Example: handle incoming commands to change mode/replace ball/etc.
        pass

class RootWidget(BoxLayout):
    pass

class MiniGolfApp(App):
    def build(self):
        return RootWidget()

if __name__ == "__main__":
    MiniGolfApp().run()