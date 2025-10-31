import math
import traceback
from kivy.app import App
from kivy.properties import ListProperty, NumericProperty, StringProperty, DictProperty
from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout

# Holes defined with pos_hint (relative coordinates inside the green)
HOLES = [
    {"id": 1, "pos_hint": (0.1101, 0.6734), "radius": 7, "last_points": None},
    {"id": 2, "pos_hint": (0.3669, 0.8375), "radius": 7, "last_points": None},
    {"id": 3, "pos_hint": (0.2116, 0.2198), "radius": 7, "last_points": None},
    {"id": 4, "pos_hint": (0.7306, 0.1486), "radius": 7, "last_points": None},
    {"id": 5, "pos_hint": (0.9144, 0.3375), "radius": 7, "last_points": None},
]

MIN_READING = 0
MAX_READING = 10

class Scoreboard(Widget):
    readings = DictProperty({})      # { hole_id: points }
    display_text = StringProperty("No readings yet")

    def _update_display(self):
        if not self.readings:
            self.display_text = "No readings yet"
            return
        lines = []
        for hid in sorted(self.readings.keys()):
            pts = self.readings[hid]
            lines.append(f"H{int(hid)}: {int(pts)}")
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
    live_text = StringProperty("")            # nearest hole quick display
    live_points_by_hole = DictProperty({})    # map hole_id->last points
    ball_x = NumericProperty(-1000)
    ball_y = NumericProperty(-1000)
    holes = ListProperty(HOLES)

    def get_scaled_hole_pos(self, hole):
        """Return (x, y) pixel coords for a hole dict with pos_hint inside this widget."""
        phx, phy = hole.get("pos_hint", (0.5, 0.5))
        px = self.x + phx * max(0, self.width)
        py = self.y + phy * max(0, self.height)
        return px, py

    def on_touch_down(self, touch):
        try:
            if not self.collide_point(*touch.pos):
                return False

            local_x = touch.x - self.x
            local_y = touch.y - self.y
            
            phx = local_x / max(1.0, self.width)
            phy = local_y / max(1.0, self.height)
            print(f"pos_hint: ({phx:.4f}, {phy:.4f})")

            # show ball
            self.ball_x = local_x
            self.ball_y = local_y

            max_dist = math.hypot(max(1, self.width), max(1, self.height))
            sb = get_or_create_scoreboard()
            results = []

            # compute for every hole, update hole dicts so KV sees change
            for i, hole in enumerate(self.holes):
                hx, hy = self.get_scaled_hole_pos(hole)
                # convert hx/hy into local coords inside the green (relative to self.x/self.y)
                local_hx = hx - self.x
                local_hy = hy - self.y
                dist = math.hypot(local_hx - local_x, local_hy - local_y)
                points = self.distance_to_reading(dist, max_dist)

                new_hole = hole.copy()
                new_hole["last_points"] = points
                # replace and reassign to trigger ListProperty notifications
                self.holes[i] = new_hole
                self.holes = list(self.holes)

                self.live_points_by_hole[new_hole["id"]] = points
                results.append((new_hole["id"], points))
                if sb:
                    sb.set_reading(new_hole["id"], points)

            # update live_text showing the nearest hole (smallest points == nearest)
            if results:
                nearest = min(results, key=lambda t: t[1])
                self.live_text = str(nearest[1])
            else:
                self.live_text = ""

            # debug print
            print(f"Touch local: ({local_x:.1f}, {local_y:.1f}); readings: {self.live_points_by_hole}")

            return True
        except Exception:
            print("Unhandled exception in on_touch_down:")
            traceback.print_exc()
            return True

    def distance_to_reading(self, dist, max_dist):
        """Map distance (0..max_dist) to integer reading MIN_READING..MAX_READING."""
        norm = 0.0 if (max_dist is None or max_dist <= 0) else min(1.0, dist / max_dist)
        cont = MIN_READING + norm * (MAX_READING - MIN_READING)
        pts = int(round(cont))
        pts = max(MIN_READING, min(MAX_READING, pts))
        return pts

class RootWidget(BoxLayout):
    pass

class MiniGolfApp(App):
    def build(self):
        return RootWidget()

if __name__ == "__main__":
    MiniGolfApp().run()