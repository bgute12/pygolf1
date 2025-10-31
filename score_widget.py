# score_widget.py
from kivy.uix.widget import Widget
from kivy.properties import ListProperty
import time

class Scoreboard(Widget):
    scores = ListProperty([])  # list of dicts: {"hole": id, "points": pts, "time": ts}

    def add_score(self, hole, points):
        self.scores.insert(0, {"hole": hole, "points": points, "time": int(time.time())})
        # keep it short
        self.scores = self.scores[:10]

    def clear(self):
        self.scores = []

    def _format_scores(self):
        if not self.scores:
            return "No scores yet"
        lines = []
        for s in self.scores:
            lines.append(f"H{s.get('hole')}  +{s.get('points')}")
        return "\n".join(lines)