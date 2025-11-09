from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.properties import BooleanProperty, NumericProperty, ListProperty, StringProperty
from kivy.graphics import Color, Ellipse
import random

class GolfGreen(Widget):
    game_started = BooleanProperty(False)
    current_round = NumericProperty(1)
    current_player_index = NumericProperty(0)
    players = ListProperty([])
    current_player = StringProperty(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ball = None
        self.ball_size = 20
        self.scores = {}
        self.holes = {
            1: (150, 200),
            2: (300, 250),
            3: (450, 300),
            4: (600, 350),
            5: (750, 400),
        }
        self.hole_points = {
            1: 5,
            2: 10,
            3: 15,
            4: 20,
            5: 25,
        }

    # ---------------------------
    # GAME SETUP
    # ---------------------------
    def register_players(self, count):
        self.players = [f"Player {i+1}" for i in range(count)]
        self.scores = {p: 0 for p in self.players}
        self.current_player_index = 0
        self.current_player = self.players[0] if self.players else None
        print("Registered players:", self.players)
        self.update_scores_display()

    def start_game(self):
        if not self.players:
            print("No players registered!")
            return
        self.game_started = True
        self.current_round = 1
        self.current_player_index = 0
        self.current_player = self.players[0]
        self.place_ball()
        print("Game started with players:", self.players)
        self.update_scores_display()

    # ---------------------------
    # BALL LOGIC
    # ---------------------------
    def place_ball(self):
        if not self.game_started:
            return
        with self.canvas:
            Color(1, 1, 1)
            x, y = random.randint(50, 700), random.randint(50, 400)
            self.ball = Ellipse(pos=(x, y), size=(self.ball_size, self.ball_size))
        print(f"Placed ball for {self.current_player} at {x}, {y}")

    def replace_ball(self):
        if not self.game_started:
            return
        if self.ball:
            self.canvas.remove(self.ball)
        self.place_ball()

    # ---------------------------
    # SCORING LOGIC
    # ---------------------------
    def on_ball_in_hole(self, hole_number):
        if not self.game_started or not self.current_player:
            return

        points = self.hole_points.get(hole_number, 0)
        self.scores[self.current_player] += points
        print(f"{self.current_player} scored {points} points on hole {hole_number}")

        # Update display on the side panel
        self.update_scores_display()

    def get_player_score(self, player):
        return self.scores.get(player, 0)

    # ---------------------------
    # PLAYER TURN LOGIC
    # ---------------------------
    def next_player(self):
        if not self.players:
            return
        self.current_player_index = (self.current_player_index + 1) % len(self.players)
        self.current_player = self.players[self.current_player_index]
        print("Next player:", self.current_player)
        self.update_scores_display()

    # ---------------------------
    # UI UPDATE LOGIC
    # ---------------------------
    def update_scores_display(self):
        """Refresh the score list shown in the KV side panel."""
        try:
            root = App.get_running_app().root
            players_label = root.ids.players_label
            players_label.text = '\n'.join(
                [f"{p}: {self.get_player_score(p)}" for p in self.players]
            ) if self.players else "No players"
        except Exception as e:
            print("Score display update error:", e)


class RootWidget(BoxLayout):
    pass


class GolfApp(App):
    def build(self):
        return RootWidget()


if __name__ == "__main__":
    GolfApp().run()
