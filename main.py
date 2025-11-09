import math
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
    mode_selected = BooleanProperty(True)  # always normal mode
    mode = StringProperty("Normal")

    ball_radius = NumericProperty(6)
    _accept_touches = False  # for startup ghost touches

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
                        size=(hole["radius"]*2, hole["radius"]*2))
            # draw ball
            if self.ball_placed:
                Color(1, 1, 1, 1)
                Ellipse(pos=(self.x + self.ball_x - self.ball_radius, self.y + self.ball_y - self.ball_radius),
                        size=(self.ball_radius*2, self.ball_radius*2))

        # update hole labels
        try:
            root = App.get_running_app().root
            if root and hasattr(root, 'ids'):
                for i, hole in enumerate(self.holes, start=1):
                    lbl = root.ids.get(f"h{i}")
                    if lbl:
                        hx, hy = self.get_scaled_hole_pos(hole)
                        lbl.pos = (hx - lbl.width/2, hy + 12)
                        lp = hole.get("last_points")
                        lbl.text = f"H{i}: {lp if lp is not None else '-'}"
        except Exception:
            pass

    def get_scaled_hole_pos(self, hole):
        phx, phy = hole.get("pos_hint", (0.5, 0.5))
        px = self.x + phx * max(1, self.width)
        py = self.y + phy * max(1, self.height)
        return px, py

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
        # reset holes
        self.holes = [{**h, "last_points": None} for h in HOLES]
        self.update_canvas()
        print("Registered players:", self.players)

    def start_game(self):
        if not self.players:
            print("No players registered!")
            return
        self.game_started = True
        self.current_player_index = 0
        self.current_player = self.players[0]
        self.ball_x = -1000
        self.ball_y = -1000
        self.ball_placed = False
        self.update_canvas()
        print("Game started. Current player:", self.current_player)

    def replace_ball(self):
        if not self.game_started or self.current_player_index != 0:
            return
        self.ball_x = -1000
        self.ball_y = -1000
        self.ball_placed = False
        # reset last_points
        self.holes = [{**h, "last_points": None} for h in HOLES]
        self.update_canvas()
        print("Ball replaced for first player.")

    def next_player(self):
        if not self.players:
            return
        self.current_player_index += 1
        if self.current_player_index >= len(self.players):
            self.current_player_index = 0
            self.current_round += 1
            # reset ball for new round
            self.ball_placed = False
            self.ball_x = -1000
            self.ball_y = -1000
            self.holes = [{**h, "last_points": None} for h in HOLES]
        self.current_player = self.players[self.current_player_index]
        self.update_canvas()
        print(f"Next player: {self.current_player} (Round {self.current_round})")

    def on_touch_down(self, touch):
        if not self._accept_touches:
            return True
        if not (self.mode_selected and self.mode == "Normal" and self.game_started):
            return False

        # prevent touching side panel
        root = App.get_running_app().root
        side = root.ids.get("side_panel")
        if side and side.collide_point(*touch.pos):
            return False

        if not self.collide_point(*touch.pos):
            return False

        if self.ball_placed:
            print("Ball already placed this round; ignoring touch.")
            return True

        self._touch_x = touch.x - self.x
        self._touch_y = touch.y - self.y
        Clock.schedule_once(self._place_ball, 0.2)  # short delay
        return True

    def _place_ball(self, dt):
        if self.ball_placed:
            return
        self.ball_x = getattr(self, "_touch_x", -1000)
        self.ball_y = getattr(self, "_touch_y", -1000)
        self.ball_placed = True
        # update last_points for holes
        max_dist = math.hypot(self.width, self.height)
        for i, hole in enumerate(self.holes):
            hx, hy = self.get_scaled_hole_pos(hole)
            dist = math.hypot(hx - self.x - self.ball_x, hy - self.y - self.ball_y)
            pts = int(round(min(MAX_READING, max(MIN_READING, dist / max_dist * MAX_READING))))
            self.holes[i]["last_points"] = pts
        # add score
        if self.current_player:
            self.player_scores.setdefault(self.current_player, []).append(MAX_READING)
        self.update_canvas()
        print(f"Ball placed for {self.current_player} at ({self.ball_x:.1f},{self.ball_y:.1f})")


class RootWidget(BoxLayout):
    pass


class MiniGolfApp(App):
    def build(self):
        return RootWidget()


if __name__ == "__main__":
    MiniGolfApp().run()
