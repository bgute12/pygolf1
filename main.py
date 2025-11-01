import math
import traceback
from kivy.app import App
from kivy.properties import ListProperty, NumericProperty, StringProperty, DictProperty
from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout

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

class Scoreboard(Widget):
    readings = DictProperty({})
    display_text = StringProperty("No readings yet")

    def _update_display(self):
        if not self.readings:
            self.display_text = "No readings yet"
            return
        lines = [f"H{int(hid)}: {int(pts)}" for hid, pts in sorted(self.readings.items())]
        self.display_text = "\n".join(lines)

    def on_readings(self, instance, value):
        self._update_display()

    def set_reading(self, hole, points):
        self.readings[hole] = points
        self._update_display()

    def clear(self):
        self.readings = {}
        self._update_display()

def get_or_create_scoreboard():
    app = App.get_running_app()
    if not app or not getattr(app, "root", None):
        return None
    root = app.root
    sb = root.ids.get("scoreboard_widget")
    if sb:
        return sb
    sb = Scoreboard()
    sb.size_hint_x = None
    sb.width = 0
    try:
        root.add_widget(sb)
    except Exception:
        pass
    root.ids["scoreboard_widget"] = sb
    return sb

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
    holes = ListProperty(HOLES)
    ball_placed = False

    def add_player_name(self, name):
        name = name.strip()
        if name and name not in self.players and len(self.players) < MAX_PLAYERS:
            self.players.append(name)
            self.player_scores[name] = []
            print(f"Added player: {name}")

    def register_players(self, count=1):
        count = max(1, min(count, MAX_PLAYERS))
        self.players = [f"Player {i+1}" for i in range(count)]
        self.player_scores = {name: [] for name in self.players}
        self.current_player_index = 0
        self.current_round = 1
        self.current_player = self.players[0] if self.players else ""
        print(f"Starting game with players: {self.players}")

    def get_current_player(self):
        return self.players[self.current_player_index] if self.players else None

    def next_player(self):
        if not self.players:
            return
        self.current_player_index += 1
        if self.current_player_index >= len(self.players):
            self.current_player_index = 0
            self.current_round += 1
            if self.current_round > MAX_ROUNDS:
                print("Game over!")
                return
        self.current_player = self.players[self.current_player_index]
        print(f"Next turn: {self.current_player} (Round {self.current_round})")
        self.ball_placed = False

    def get_scaled_hole_pos(self, hole):
        phx, phy = hole.get("pos_hint", (0.5, 0.5))
        px = self.x + phx * max(0, self.width)
        py = self.y + phy * max(0, self.height)
        return px, py

    def on_touch_down(self, touch):
        try:
            if not self.collide_point(*touch.pos):
                return False

            local_x, local_y = self.to_local(*touch.pos)

            self._handle_touch(local_x, local_y)
            return True
        except Exception:
            print("Unhandled exception in on_touch_down:")
            traceback.print_exc()
            return True

    def _handle_touch(self, local_x, local_y):
        if self.ball_placed:
            return  # Ignore additional touches after ball is placed

        max_dist = math.hypot(max(1, self.width), max(1, self.height))
        sb = get_or_create_scoreboard()
        results = []

        for i, hole in enumerate(self.holes):
            hx, hy = self.get_scaled_hole_pos(hole)
            local_hx = hx - self.x
            local_hy = hy - self.y
            dist = math.hypot(local_hx - local_x, local_hy - local_y)
            points = self.distance_to_reading(dist, max_dist)

            new_hole = hole.copy()
            new_hole["last_points"] = points
            self.holes[i] = new_hole
            self.holes = list(self.holes)

            self.live_points_by_hole[new_hole["id"]] = points
            results.append((new_hole["id"], points))
            if sb:
                sb.set_reading(new_hole["id"], points)

        if results:
            nearest = min(results, key=lambda t: t[1])
            self.live_text = str(nearest[1])
            hit = nearest[1] == 0
            current_player = self.get_current_player()
            score = MAX_READING if hit else 0
            if current_player:
                self.player_scores[current_player].append(score)
                print(f"{current_player} scored {score} in round {self.current_round}")
        else:
            self.live_text = ""

        if not self.ball_placed:
            self.ball_x = local_x
            self.ball_y = local_y
            percent_x = local_x / float(self.width) if self.width else 0
            percent_y = local_y / float(self.height) if self.height else 0
            print(f"Ball pos_hint: ({percent_x:.4f}, {percent_y:.4f})")
            self.ball_placed = True
    def distance_to_reading(self, dist, max_dist):
        norm = 0.0 if (max_dist is None or max_dist <= 0) else min(1.0, dist / max_dist)
        cont = MIN_READING + norm * (MAX_READING - MIN_READING)
        pts = int(round(cont))
        return max(MIN_READING, min(MAX_READING, pts))

class RootWidget(BoxLayout):
    pass

class MiniGolfApp(App):
    def build(self):
        return RootWidget()

if __name__ == "__main__":
    MiniGolfApp().run()