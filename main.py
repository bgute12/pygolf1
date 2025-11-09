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

    # New: only one placement allowed per round
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
        # mark that this round had a placement and immediately advance to next round
        self.placed_this_round = True
        self.current_round += 1
        # reset placed flag for next round (so next round starts with no placement)
        # but we want to set it false after increment so next round allows placement
        self.placed_this_round = False
        # keep current_player_index at 0 for new round (optional: rotate which player starts)
        self.current_player_index = 0
        self.current_player = self.players[0] if self.players else ""
        print(f"--- Advanced to round {self.current_round}; placement for that round is now empty ---")

    def handle_hole_event(self, hole_id):
        if self.placed_this_round:
            print("A placement has already occurred this round; ignore.")
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
        # schedule placement in 0.5 seconds
        self._pending_place_ev = Clock.schedule_once(lambda dt: self._do_place(hx, hy, hole_id), 0.5)

    def _do_place(self, hx, hy, hole_id=None):
        self._pending_place_ev = None
        self.place_ball(hx, hy, hole_id)

    def place_ball(self, hx, hy, hole_id=None):
        if self.placed_this_round:
            print("Ignored placement; round already had a placement.")
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

        # For single placement per round: attribute score to current player
        if self.current_player:
            self.player_scores.setdefault(self.current_player, []).append(score)
            print(f"{self.current_player} scored {score} (dist={int(dist)} px) at hole {target_hole['id']}")

        # record last points for hole and update labels
        self.hole_points[target_hole["id"]] = score
        self._update_hole_labels()

        # mark that a placement happened and immediately advance the round (as requested)
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