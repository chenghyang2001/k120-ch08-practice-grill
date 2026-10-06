"""game.py 單元測試（spec §8 第 16–22 項＋§5 狀態機與提示規則）。

多數測試用手工建立的 Puzzle（Wikipedia 經典題＋已知正解），避免每個測試都跑出題器；
最後另有一組以 generate() 出題的整合測試。
"""

from __future__ import annotations

import random

import pytest

from sudoku.board import Grid
from sudoku.game import GameSession, GameState, Move
from sudoku.generator import Difficulty, Puzzle, generate

# Wikipedia「Sudoku」條目的經典題（30 個提示）與其唯一解
GIVENS = "530070000600195000098000060800060003400803001700020006060000280000419005000080079"
SOLUTION = "534678912672195348198342567859761423426853791713924856961537284287419635345286179"

# 經典題中的幾個空格與給定格，供測試指名使用
EMPTY_A = (0, 2)  # 正解 4
EMPTY_B = (0, 3)  # 正解 6
EMPTY_C = (8, 0)  # 正解 3
GIVEN_CELL = (0, 0)  # 給定 5


def to_grid(text: str) -> Grid:
    values = [int(ch) for ch in text]
    return tuple(tuple(values[r * 9 : (r + 1) * 9]) for r in range(9))


SOLUTION_GRID = to_grid(SOLUTION)


def solution_at(cell: tuple[int, int]) -> int:
    return SOLUTION_GRID[cell[0]][cell[1]]


def wrong_value(cell: tuple[int, int]) -> int:
    """回傳該格一個「非 0 且 ≠ 正解」的值。"""
    return 1 if solution_at(cell) != 1 else 2


def make_puzzle(givens: str = GIVENS, seed: int = 0) -> Puzzle:
    grid = to_grid(givens)
    return Puzzle(
        givens=grid,
        solution=SOLUTION_GRID,
        difficulty=Difficulty.MEDIUM,
        clue_count=sum(1 for row in grid for v in row if v != 0),
        seed=seed,
    )


def puzzle_with_holes(*holes: tuple[int, int]) -> Puzzle:
    """以完整解挖掉指定格，做成「差幾格就完成」的題目。"""
    chars = list(SOLUTION)
    for row, col in holes:
        chars[row * 9 + col] = "0"
    return make_puzzle("".join(chars))


@pytest.fixture
def session() -> GameSession:
    return GameSession(make_puzzle(), rng=random.Random(1))


def empty_cells(game: GameSession) -> list[tuple[int, int]]:
    return [(r, c) for r in range(9) for c in range(9) if game.board.get(r, c) == 0]


# ---------- 建構 ----------


def test_new_session_initial_state(session: GameSession) -> None:
    assert session.state is GameState.PLAYING
    assert not session.is_over
    assert session.hint_count == 0
    assert not session.can_undo()
    assert not session.can_redo()
    assert session.board.to_grid() == to_grid(GIVENS)
    assert session.puzzle == make_puzzle()


def test_board_rebuilt_from_givens_with_matching_flags(session: GameSession) -> None:
    # spec §4.3 實作約束：給定旗標必須只出現在非 0 格
    givens = to_grid(GIVENS)
    for r in range(9):
        for c in range(9):
            assert session.board.is_given(r, c) == (givens[r][c] != 0)


@pytest.mark.parametrize("bad_puzzle", [None, GIVENS, to_grid(GIVENS)])
def test_rejects_non_puzzle(bad_puzzle: object) -> None:
    with pytest.raises(TypeError):
        GameSession(bad_puzzle)  # type: ignore[arg-type]


def test_rejects_non_random_rng() -> None:
    with pytest.raises(TypeError):
        GameSession(make_puzzle(), rng=42)  # type: ignore[arg-type]


def test_rejects_givens_contradicting_solution() -> None:
    bad_givens = "6" + GIVENS[1:]  # (0, 0) 正解為 5
    with pytest.raises(ValueError):
        GameSession(make_puzzle(bad_givens))


def test_rejects_incomplete_solution() -> None:
    puzzle = Puzzle(
        givens=to_grid(GIVENS),
        solution=to_grid(GIVENS),
        difficulty=Difficulty.MEDIUM,
        clue_count=30,
        seed=0,
    )
    with pytest.raises(ValueError):
        GameSession(puzzle)


def test_move_is_frozen() -> None:
    move = Move(0, 1, 0, 5)
    with pytest.raises(AttributeError):
        move.new = 6  # type: ignore[misc]


# ---------- 16. 給定格不可改 ----------


@pytest.mark.parametrize("value", [0, 1, 5, 9])
def test_set_cell_on_given_returns_false(session: GameSession, value: int) -> None:
    before = session.board.to_grid()
    assert session.set_cell(*GIVEN_CELL, value) is False
    assert session.board.to_grid() == before
    assert not session.can_undo()


def test_clear_cell_on_given_returns_false(session: GameSession) -> None:
    assert session.clear_cell(*GIVEN_CELL) is False
    assert session.board.get(*GIVEN_CELL) == 5


def test_set_cell_on_empty_records_move(session: GameSession) -> None:
    assert session.set_cell(*EMPTY_A, 7) is True
    assert session.board.get(*EMPTY_A) == 7
    assert not session.board.is_given(*EMPTY_A)
    assert session.can_undo()


def test_set_same_value_is_noop_and_not_recorded(session: GameSession) -> None:
    session.set_cell(*EMPTY_A, 7)
    session.set_cell(*EMPTY_B, 3)
    session.undo()  # 讓 Redo 堆疊有東西，確認無操作不會把它清掉
    assert session.set_cell(*EMPTY_A, 7) is False
    assert session.clear_cell(*EMPTY_B) is False  # 已是空格，清除也是無操作
    assert session.undo() == Move(*EMPTY_A, 0, 7)
    assert session.undo() is None
    assert session.can_redo()


@pytest.mark.parametrize("bad_value", [10, -1])
def test_set_cell_value_out_of_range_raises(session: GameSession, bad_value: int) -> None:
    with pytest.raises(ValueError):
        session.set_cell(*EMPTY_A, bad_value)


@pytest.mark.parametrize(("row", "col"), [(9, 0), (0, 9), (-1, 0)])
def test_set_cell_coord_out_of_range_raises(session: GameSession, row: int, col: int) -> None:
    with pytest.raises(ValueError):
        session.set_cell(row, col, 1)


@pytest.mark.parametrize(("row", "col", "value"), [(True, 0, 1), (0, 0.0, 1), (0, 2, True)])
def test_set_cell_bad_types_raise(
    session: GameSession, row: object, col: object, value: object
) -> None:
    with pytest.raises(TypeError):
        session.set_cell(row, col, value)  # type: ignore[arg-type]


# ---------- 17. Undo / Redo ----------


def test_undo_redo_basic_flow(session: GameSession) -> None:
    session.set_cell(*EMPTY_A, 7)
    session.set_cell(*EMPTY_A, 8)
    session.set_cell(*EMPTY_B, 3)

    assert session.undo() == Move(*EMPTY_B, 0, 3)
    assert session.board.get(*EMPTY_B) == 0
    assert session.undo() == Move(*EMPTY_A, 7, 8)
    assert session.board.get(*EMPTY_A) == 7
    assert session.can_redo()

    assert session.redo() == Move(*EMPTY_A, 7, 8)
    assert session.board.get(*EMPTY_A) == 8
    assert session.redo() == Move(*EMPTY_B, 0, 3)
    assert session.board.get(*EMPTY_B) == 3
    assert session.redo() is None


def test_new_move_clears_redo(session: GameSession) -> None:
    session.set_cell(*EMPTY_A, 7)
    session.undo()
    assert session.can_redo()
    session.set_cell(*EMPTY_B, 2)
    assert not session.can_redo()
    assert session.redo() is None


def test_undo_redo_on_empty_stacks_return_none(session: GameSession) -> None:
    assert session.undo() is None
    assert session.redo() is None


def test_clear_cell_is_recorded_and_undoable(session: GameSession) -> None:
    session.set_cell(*EMPTY_A, 7)
    assert session.clear_cell(*EMPTY_A) is True
    assert session.board.get(*EMPTY_A) == 0
    assert session.undo() == Move(*EMPTY_A, 7, 0)
    assert session.board.get(*EMPTY_A) == 7


# ---------- 18. 填滿全對 → SOLVED，之後操作無效 ----------


def test_filling_all_correct_solves() -> None:
    game = GameSession(puzzle_with_holes(EMPTY_A, EMPTY_B))
    assert game.set_cell(*EMPTY_A, solution_at(EMPTY_A)) is True
    assert game.state is GameState.PLAYING
    assert game.set_cell(*EMPTY_B, solution_at(EMPTY_B)) is True
    assert game.state is GameState.SOLVED
    assert game.is_over


def test_full_but_wrong_stays_playing() -> None:
    game = GameSession(puzzle_with_holes(EMPTY_A))
    game.set_cell(*EMPTY_A, wrong_value(EMPTY_A))
    assert game.board.is_full()
    assert game.state is GameState.PLAYING
    assert game.check() == {EMPTY_A}


def test_operations_after_solved_are_ignored() -> None:
    game = GameSession(puzzle_with_holes(EMPTY_A, EMPTY_B))
    game.set_cell(*EMPTY_A, solution_at(EMPTY_A))
    game.set_cell(*EMPTY_B, solution_at(EMPTY_B))
    assert game.state is GameState.SOLVED
    snapshot = game.board.to_grid()

    assert game.set_cell(*EMPTY_A, wrong_value(EMPTY_A)) is False
    assert game.clear_cell(*EMPTY_B) is False
    assert game.undo() is None
    assert game.redo() is None
    assert game.hint() is None
    assert game.hint(*EMPTY_A) is None
    assert not game.can_undo()
    assert not game.can_redo()
    game.give_up()
    assert game.state is GameState.SOLVED
    assert game.board.to_grid() == snapshot
    assert game.hint_count == 0


def test_undo_reaching_correct_full_board_solves() -> None:
    # 填對 A → 清除 A → 對 B 提示；此時 Undo（還原清除）讓盤面填滿全對
    game = GameSession(puzzle_with_holes(EMPTY_A, EMPTY_B))
    game.set_cell(*EMPTY_A, solution_at(EMPTY_A))
    game.clear_cell(*EMPTY_A)
    assert game.hint(*EMPTY_B) == EMPTY_B
    assert game.state is GameState.PLAYING
    assert game.undo() == Move(*EMPTY_A, solution_at(EMPTY_A), 0)
    assert game.state is GameState.SOLVED


# ---------- 19. give_up ----------


def test_give_up_fills_solution_and_ends(session: GameSession) -> None:
    session.set_cell(*EMPTY_A, wrong_value(EMPTY_A))
    session.give_up()
    assert session.state is GameState.GAVE_UP
    assert session.is_over
    assert session.board.to_grid() == SOLUTION_GRID
    assert session.check() == set()


def test_operations_after_give_up_are_ignored(session: GameSession) -> None:
    session.set_cell(*EMPTY_A, 7)
    session.give_up()
    assert session.set_cell(*EMPTY_B, 1) is False
    assert session.clear_cell(*EMPTY_A) is False
    assert session.undo() is None
    assert session.redo() is None
    assert session.hint() is None
    assert not session.can_undo()
    session.give_up()  # 再按一次不應改變任何東西
    assert session.state is GameState.GAVE_UP
    assert session.board.to_grid() == SOLUTION_GRID


# ---------- 20. 提示 × Undo 衝突（spec 決策 12 的 4 步情境） ----------


def test_hint_filters_undo_history_for_hinted_cell(session: GameSession) -> None:
    # 1. 填錯 A 格
    assert session.set_cell(*EMPTY_A, wrong_value(EMPTY_A)) is True
    # 2. 填 B 格
    assert session.set_cell(*EMPTY_B, 9) is True
    # 3. 對 A 格提示
    assert session.hint(*EMPTY_A) == EMPTY_A
    # 4. 連按兩次 Undo：第一次還原 B，第二次因 A 的紀錄已濾除而回傳 None
    assert session.undo() == Move(*EMPTY_B, 0, 9)
    assert session.board.get(*EMPTY_B) == 0
    assert session.undo() is None
    assert session.board.get(*EMPTY_A) == solution_at(EMPTY_A)
    assert session.board.is_given(*EMPTY_A)
    assert session.hint_count == 1


def test_hint_clears_redo(session: GameSession) -> None:
    session.set_cell(*EMPTY_B, 9)
    session.undo()
    assert session.can_redo()
    session.hint(*EMPTY_A)
    assert not session.can_redo()
    assert session.redo() is None


# ---------- 21. 提示計次、提示格被鎖定 ----------


def test_hint_on_selected_empty_cell(session: GameSession) -> None:
    assert session.hint(*EMPTY_C) == EMPTY_C
    assert session.board.get(*EMPTY_C) == solution_at(EMPTY_C)
    assert session.board.is_given(*EMPTY_C)
    assert session.hint_count == 1


def test_hinted_cell_is_locked(session: GameSession) -> None:
    session.hint(*EMPTY_A)
    assert session.set_cell(*EMPTY_A, wrong_value(EMPTY_A)) is False
    assert session.clear_cell(*EMPTY_A) is False
    assert session.board.get(*EMPTY_A) == solution_at(EMPTY_A)


def test_hint_count_accumulates(session: GameSession) -> None:
    for expected in range(1, 4):
        assert session.hint() is not None
        assert session.hint_count == expected


def test_hint_on_given_cell_falls_back_to_random(session: GameSession) -> None:
    target = session.hint(*GIVEN_CELL)
    assert target is not None
    assert target != GIVEN_CELL
    assert to_grid(GIVENS)[target[0]][target[1]] == 0
    assert session.hint_count == 1


def test_hint_on_correct_cell_falls_back_to_random(session: GameSession) -> None:
    session.set_cell(*EMPTY_A, solution_at(EMPTY_A))
    target = session.hint(*EMPTY_A)
    assert target is not None
    assert target != EMPTY_A
    # 填對但未提示的格子不會被鎖定
    assert not session.board.is_given(*EMPTY_A)


def test_random_hint_prefers_empty_or_wrong_cells(session: GameSession) -> None:
    # 把除了 A、B 之外的空格都填對，A 留空、B 填錯：隨機提示只能落在 A 或 B
    for cell in empty_cells(session):
        if cell not in (EMPTY_A, EMPTY_B):
            session.set_cell(*cell, solution_at(cell))
    session.set_cell(*EMPTY_B, wrong_value(EMPTY_B))
    first = session.hint()
    assert first in (EMPTY_A, EMPTY_B)
    second = session.hint()
    assert {first, second} == {EMPTY_A, EMPTY_B}
    # 兩格都提示完 → 填滿全對
    assert session.state is GameState.SOLVED
    assert session.hint() is None


def test_random_hint_is_reproducible_with_fixed_rng() -> None:
    first = GameSession(make_puzzle(), rng=random.Random(7))
    second = GameSession(make_puzzle(), rng=random.Random(7))
    first_cells = [first.hint() for _ in range(5)]
    second_cells = [second.hint() for _ in range(5)]
    assert first_cells == second_cells
    assert len(set(first_cells)) == 5


def test_default_rng_derived_from_puzzle_seed_is_reproducible() -> None:
    first = GameSession(make_puzzle(seed=99))
    second = GameSession(make_puzzle(seed=99))
    assert [first.hint() for _ in range(5)] == [second.hint() for _ in range(5)]


def test_hint_that_completes_board_solves() -> None:
    game = GameSession(puzzle_with_holes(EMPTY_C))
    assert game.hint() == EMPTY_C
    assert game.state is GameState.SOLVED
    assert game.hint_count == 1


def test_hint_with_only_row_raises(session: GameSession) -> None:
    with pytest.raises(TypeError):
        session.hint(0, None)
    assert session.hint_count == 0


def test_hint_coord_out_of_range_raises(session: GameSession) -> None:
    with pytest.raises(ValueError):
        session.hint(9, 9)


# ---------- 22. check 與 has_progress ----------


def test_check_reports_only_wrong_filled_cells(session: GameSession) -> None:
    assert session.check() == set()
    session.set_cell(*EMPTY_A, wrong_value(EMPTY_A))
    session.set_cell(*EMPTY_B, solution_at(EMPTY_B))
    session.set_cell(*EMPTY_C, wrong_value(EMPTY_C))
    assert session.check() == {EMPTY_A, EMPTY_C}


def test_check_flags_value_conflicting_with_given(session: GameSession) -> None:
    # 與給定格同列重複的值也是錯格（因為一定 ≠ 正解）
    session.set_cell(*EMPTY_A, 5)  # 第 0 列已有給定 5
    assert EMPTY_A in session.check()


def test_has_progress_false_for_fresh_session(session: GameSession) -> None:
    assert session.has_progress() is False


def test_has_progress_after_fill(session: GameSession) -> None:
    session.set_cell(*EMPTY_A, 7)
    assert session.has_progress() is True


def test_has_progress_after_fill_then_undo(session: GameSession) -> None:
    session.set_cell(*EMPTY_A, 7)
    session.undo()
    # 盤面已回到初始，但玩家確實操作過（Redo 可還原），仍算有進度
    assert session.board.to_grid() == to_grid(GIVENS)
    assert session.has_progress() is True


def test_has_progress_after_hint_only(session: GameSession) -> None:
    session.hint()
    assert session.has_progress() is True


# ---------- 整合：以出題器產生的題目完整遊玩 ----------


def test_generated_puzzle_play_through_to_solved() -> None:
    puzzle = generate(Difficulty.MEDIUM, seed=3)
    game = GameSession(puzzle)
    assert game.board.to_grid() == puzzle.givens
    assert not game.has_progress()
    for row, col in empty_cells(game):
        assert game.set_cell(row, col, puzzle.solution[row][col]) is True
    assert game.state is GameState.SOLVED
    assert game.board.to_grid() == puzzle.solution
    assert game.check() == set()
