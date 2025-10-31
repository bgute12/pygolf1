# main.py
import math
import time
import traceback
from kivy.app import App
from kivy.properties import ListProperty, NumericProperty, StringProperty
from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout
from kivy.clock import Clock

# Single hole (local coordinates inside GolfGreen)
HOLES = [
    {"id": 1, "pos": (450, 250), "radius": 28},
]

# Reading range 1..5 (1 = closest, 5 = farthest)
MIN_READING = 0
MAX_READING = 6

class Scoreboard(Widget):
    scores = ListProperty([])
    display_text = StringProperty("No readings yet")

    def _update_display(self):
        if not self.scores:
            self.display_text = "No readings yet"
        else:
            lines = [f"H{int(s['hole'])}: {int(s['points'])}" for s in self.scores]
            self.display_text = "\n".join(lines)

    def on_scores(self, instance, value):
        self._update_display()

    def add_score(self, hole, points):
        # newest first, keep recent entries
        self.scores.insert(0, {"hole": hole, "points": points, "time": int(time.time())})
        self.scores = self.scores[:20]
        self._update_display()

    def clear(self):
        self.scores = []
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
    live_text = StringProperty("")
    ball_x = NumericProperty(-1000)
    ball_y = NumericProperty(-1000)
    holes = ListProperty(HOLES)

    def on_touch_down(self, touch):
        try:
            if not self.collide_point(*touch.pos):
                return False

            # convert to local coordinates
            local_x = touch.x - self.x
            local_y = touch.y - self.y

            # place ball visually
            self.ball_x = local_x
            self.ball_y = local_y

            # Since there's only one hole, use it directly
            target = self.holes[0] if self.holes else None
            if not target:
                return True
            hx, hy = target["pos"]
            dist = math.hypot(hx - local_x, hy - local_y)

            # normalize by the green diagonal so mapping is consistent
            max_dist = math.hypot(max(1, self.width), max(1, self.height))
            points = self.distance_to_reading_1_to_5(dist, max_dist)

            sb = get_or_create_scoreboard()
            if sb:
                sb.add_score(target["id"], points)
            else:
                print("Scoreboard missing; reading:", target["id"], points)
            return True
        except Exception:
            print("Unhandled exception in on_touch_down:")
            traceback.print_exc()
            return True

    def distance_to_reading_1_to_5(self, dist, max_dist):
        """
        Map distance (0..max_dist) to integer reading 1..5 (1 = closest, 5 = farthest).
        Safely handles max_dist == 0 and updates self.live_text (requires live_text = StringProperty("") on the class).
        """
        norm = 0.0 if (max_dist is None or max_dist <= 0) else min(1.0, dist / max_dist)
        cont = MIN_READING + norm * (MAX_READING - MIN_READING)
        pts = int(round(cont))
        pts = max(MIN_READING, min(MAX_READING, pts))
        # update live_text for KV binding
        try:
            self.live_text = str(pts)
        except Exception:
            pass
        print(pts)
        return pts

class RootWidget(BoxLayout):
    live_pts = StringProperty("-")

    def on_kv_post(self, base_widget):
        # bind golf.live_text -> root.live_pts once ids are available
        golf = self.ids.get("golf")
        if golf:
            self.live_pts = golf.live_text
            golf.bind(live_text=lambda inst, val: setattr(self, "live_pts", val))

class MiniGolfApp(App):
    def build(self):
        return RootWidget()

if __name__ == "__main__":
    MiniGolfApp().run()