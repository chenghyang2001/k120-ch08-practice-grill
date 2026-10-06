"""數獨單局遊戲狀態：填數、Undo/Redo、提示、檢查、放棄（spec §4.4、§5）。

GUI 只透過 GameSession 操作盤面，所有規則（給定格鎖定、狀態機、提示與 Undo 的互動）
集中在這裡，讓規則能脫離視窗單元測試。本模組不得 import tkinter。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum, auto

from sudoku.board import EMPTY, SIZE, Board, Grid, _validate_value
from sudoku.generator import Puzzle

Cell = tuple[int, int]


class GameState(Enum):
    """單局狀態機：PLAYING 只會單向轉為 SOLVED 或 GAVE_UP，不會轉回。"""

    PLAYING = auto()
    SOLVED = auto()
    GAVE_UP = auto()


@dataclass(frozen=True)
class Move:
    """一次玩家填數；每筆只記單格，Undo 還原 old、Redo 重做 new。"""

    row: int
    col: int
    old: int
    new: int


def _validate_puzzle(puzzle: object) -> None:
    """題目型別錯誤拋 TypeError；正解不完整/不合法或給定數與正解矛盾拋 ValueError。

    提示與勝負判定都以 solution 為準，題目資料若自相矛盾，
    玩家會遇到「照提示填了卻永遠不算過關」，因此在開局就擋下。
    """
    if not isinstance(puzzle, Puzzle):
        raise TypeError(f"puzzle 必須是 Puzzle，收到 {type(puzzle).__name__}")
    solution_board = Board.from_grid(puzzle.solution)
    if not solution_board.is_full() or solution_board.conflicts():
        raise ValueError("puzzle.solution 必須是填滿且無衝突的完整解")
    givens_board = Board.from_grid(puzzle.givens)
    for row in range(SIZE):
        for col in range(SIZE):
            value = givens_board.get(row, col)
            if value != EMPTY and value != solution_board.get(row, col):
                raise ValueError(f"給定數與正解矛盾：({row}, {col}) = {value}")


class GameSession:
    """一局數獨。set_cell / clear_cell / undo / redo / hint / give_up 是僅有的修改入口。

    board 屬性回傳的是遊戲內部盤面本身（供 GUI 讀取繪製），呼叫端不得直接修改它，
    否則會繞過給定格鎖定與 Undo 紀錄。
    """

    def __init__(self, puzzle: Puzzle, rng: random.Random | None = None) -> None:
        """以題目開一局。

        盤面一律用 Board.from_grid(puzzle.givens) 重建：挖洞過程中的 Board 會殘留
        給定旗標（spec §4.3 實作約束），不能直接沿用。
        rng 只用於提示隨機挑格；預設以 puzzle.seed 建立，讓同一題的提示順序可重現，
        測試也可注入固定 rng。

        puzzle 不是 Puzzle、rng 不是 random.Random → TypeError；題目自相矛盾 → ValueError。
        """
        _validate_puzzle(puzzle)
        if rng is not None and not isinstance(rng, random.Random):
            raise TypeError(f"rng 必須是 random.Random 或 None，收到 {type(rng).__name__}")
        self._puzzle = puzzle
        self._solution: Grid = Board.from_grid(puzzle.solution).to_grid()
        self._board = Board.from_grid(puzzle.givens)
        self._rng = rng if rng is not None else random.Random(puzzle.seed)
        self._state = GameState.PLAYING
        self._hint_count = 0
        self._undo_stack: list[Move] = []
        self._redo_stack: list[Move] = []
        # 題目若一開始就填滿（理論上不會出現），直接視為已解，避免卡在無事可做的 PLAYING
        self._update_solved()

    # ---------- 唯讀屬性 ----------

    @property
    def puzzle(self) -> Puzzle:
        """本局題目。"""
        return self._puzzle

    @property
    def board(self) -> Board:
        """目前盤面（內部物件本身，僅供讀取）。"""
        return self._board

    @property
    def state(self) -> GameState:
        """目前狀態。"""
        return self._state

    @property
    def hint_count(self) -> int:
        """本局已使用的提示次數。"""
        return self._hint_count

    @property
    def is_over(self) -> bool:
        """本局是否已結束（SOLVED 或 GAVE_UP），結束後盤面鎖定。"""
        return self._state is not GameState.PLAYING

    # ---------- 填數 ----------

    def set_cell(self, row: int, col: int, value: int) -> bool:
        """填入數值（0 表示清除），成功改變盤面才回傳 True。

        回傳 False 的情況（盤面與 Undo/Redo 堆疊皆不變）：
        - 本局已結束（非 PLAYING）
        - 該格為給定格（題目原有或已被提示鎖定）
        - 新值與目前值相同：視為無操作，不推入 Undo、也不清空 Redo，
          避免玩家重按同一數字就把可 Redo 的紀錄洗掉

        值改變時推入 Undo、清空 Redo；之後若填滿且全對 → SOLVED。
        座標或數值越界 → ValueError；型別錯誤（非 int、bool）→ TypeError。
        參數驗證先於狀態判斷，讓錯誤呼叫在任何狀態下都會被發現。
        """
        old = self._board.get(row, col)
        _validate_value(value)
        if self.is_over or self._board.is_given(row, col) or old == value:
            return False
        self._board.set(row, col, value)
        self._undo_stack.append(Move(row, col, old, value))
        self._redo_stack.clear()
        self._update_solved()
        return True

    def clear_cell(self, row: int, col: int) -> bool:
        """清除格子，等同 set_cell(row, col, 0)。"""
        return self.set_cell(row, col, EMPTY)

    # ---------- Undo / Redo ----------

    def undo(self) -> Move | None:
        """還原最近一筆玩家填數，回傳該 Move；無可還原或本局已結束回傳 None。

        提示會改動其他格，濾除後的 Undo 紀錄還原後可能恰好填滿且全對，
        因此還原後同樣檢查是否轉為 SOLVED。
        """
        if self.is_over or not self._undo_stack:
            return None
        move = self._undo_stack.pop()
        self._board.set(move.row, move.col, move.old)
        self._redo_stack.append(move)
        self._update_solved()
        return move

    def redo(self) -> Move | None:
        """重做最近一筆被還原的填數，回傳該 Move；無可重做或本局已結束回傳 None。

        重做後若填滿且全對 → SOLVED，與 set_cell 的判定一致。
        """
        if self.is_over or not self._redo_stack:
            return None
        move = self._redo_stack.pop()
        self._board.set(move.row, move.col, move.new)
        self._undo_stack.append(move)
        self._update_solved()
        return move

    def can_undo(self) -> bool:
        """目前能否 Undo（GUI 用來啟用/停用按鈕）。"""
        return not self.is_over and bool(self._undo_stack)

    def can_redo(self) -> bool:
        """目前能否 Redo（GUI 用來啟用/停用按鈕）。"""
        return not self.is_over and bool(self._redo_stack)

    # ---------- 提示 ----------

    def hint(self, row: int | None = None, col: int | None = None) -> Cell | None:
        """在一格填入正解並鎖定，回傳該格座標；本局已結束或無可提示格回傳 None。

        選格規則（spec §5）：有選格、該格非給定且值 ≠ 正解 → 提示該格；
        否則從「空格或錯格」中以本局 rng 隨機挑一格。
        提示不可 Undo：會從 Undo 堆疊濾除所有涉及該格的 Move（否則 Undo 會把鎖定格改回去），
        並清空 Redo（Redo 紀錄建立在提示前的盤面上，已失去意義）。

        row 與 col 只給其中一個 → TypeError；座標越界 → ValueError。
        """
        target = self._pick_hint_cell(row, col)
        if self.is_over or target is None:
            return None
        hint_row, hint_col = target
        self._board.set(hint_row, hint_col, self._solution[hint_row][hint_col])
        self._board.lock(hint_row, hint_col)
        self._hint_count += 1
        self._undo_stack = [m for m in self._undo_stack if (m.row, m.col) != target]
        self._redo_stack.clear()
        self._update_solved()
        return target

    def _pick_hint_cell(self, row: int | None, col: int | None) -> Cell | None:
        """決定提示哪一格；先驗證參數，再依 spec §5 規則挑格。"""
        if (row is None) != (col is None):
            raise TypeError("hint 的 row 與 col 必須同時提供或同時省略")
        if row is not None and col is not None:
            self._board.get(row, col)  # 借 Board 驗證座標型別與範圍
            if self._needs_hint(row, col):
                return row, col
        if self.is_over:
            return None
        # 依列優先排序後再抽，讓同一 rng 狀態永遠挑到同一格（可重現）
        eligible = [(r, c) for r in range(SIZE) for c in range(SIZE) if self._needs_hint(r, c)]
        if not eligible:
            return None
        return self._rng.choice(eligible)

    def _needs_hint(self, row: int, col: int) -> bool:
        """非給定且值 ≠ 正解（即空格或錯格）才值得提示。"""
        if self._board.is_given(row, col):
            return False
        return self._board.get(row, col) != self._solution[row][col]

    # ---------- 檢查 / 放棄 / 進度 ----------

    def check(self) -> set[Cell]:
        """回傳已填（非 0）且與正解不符的格子；空格不算錯。"""
        return {
            (row, col)
            for row in range(SIZE)
            for col in range(SIZE)
            if self._board.get(row, col) not in (EMPTY, self._solution[row][col])
        }

    def give_up(self) -> None:
        """放棄本局（自動解）：盤面填入正解、state → GAVE_UP；本局已結束時無作用。

        Undo/Redo 一併清空：結束後本就不可用，清掉避免殘留紀錄被誤讀為可還原。
        """
        if self.is_over:
            return
        for row in range(SIZE):
            for col in range(SIZE):
                self._board.set(row, col, self._solution[row][col])
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._state = GameState.GAVE_UP

    def has_progress(self) -> bool:
        """玩家目前或曾經有操作過盤面（GUI 開新局前用來決定是否先確認）。

        以下任一成立即為 True：
        - Undo 或 Redo 堆疊非空（填過數字，即使之後清除或還原也算）
        - 用過提示（提示格已鎖定、紀錄被濾除，但仍是本局的投入）
        - 盤面上有非給定的非 0 格（防禦性檢查，正常流程已被前兩項涵蓋）
        """
        if self._undo_stack or self._redo_stack or self._hint_count > 0:
            return True
        return any(
            self._board.get(row, col) != EMPTY and not self._board.is_given(row, col)
            for row in range(SIZE)
            for col in range(SIZE)
        )

    # ---------- 內部 ----------

    def _update_solved(self) -> None:
        """PLAYING 中若盤面與正解完全相同（即填滿且全對）→ SOLVED。"""
        if self._state is GameState.PLAYING and self._board.to_grid() == self._solution:
            self._state = GameState.SOLVED
