"""solver.py 單元測試（spec §8 第 5–9 項＋§7 邊界條件）。"""

from __future__ import annotations

import time

import pytest

from sudoku.board import Board
from sudoku.solver import count_solutions, solve

PUZZLE = "530070000600195000098000060800060003400803001700020006060000280000419005000080079"
SOLUTION = "534678912672195348198342567859761423426853791713924856961537284287419635345286179"
# Arto Inkala 2012「世界最難數獨」
HARDEST = "800000000003600000070090200050007000000045700000100030001000068008500010090000400"
EMPTY_STRING = "0" * 81

# 解題時間上限（spec：世界最難數獨應在 1 秒內解完）
HARDEST_TIME_LIMIT_SECONDS = 1.0


def assert_valid_solution(solved: Board, original: Board) -> None:
    """檢查解答：填滿、無衝突、每行列宮恰為 1–9、保留給定數與給定旗標。"""
    assert solved.is_full()
    assert solved.conflicts() == set()
    grid = solved.to_grid()
    digits = set(range(1, 10))
    for i in range(9):
        assert set(grid[i]) == digits
        assert {grid[r][i] for r in range(9)} == digits
    for box_row in range(0, 9, 3):
        for box_col in range(0, 9, 3):
            box = {
                grid[r][c]
                for r in range(box_row, box_row + 3)
                for c in range(box_col, box_col + 3)
            }
            assert box == digits
    for r in range(9):
        for c in range(9):
            if original.get(r, c) != 0:
                assert solved.get(r, c) == original.get(r, c)
            assert solved.is_given(r, c) == original.is_given(r, c)


# ---------- 5. 解出一般題 ----------


def test_solve_normal_puzzle() -> None:
    board = Board.from_string(PUZZLE)
    solved = solve(board)
    assert solved is not None
    assert_valid_solution(solved, board)
    assert solved.to_string() == SOLUTION


def test_solve_already_solved_board_returns_equal_copy() -> None:
    board = Board.from_string(SOLUTION)
    solved = solve(board)
    assert solved is not None
    assert solved == board
    assert solved is not board


def test_solve_partially_filled_by_player() -> None:
    # 玩家填入（非給定）的正確值也應被保留，且不變成給定格
    board = Board.from_string(PUZZLE)
    board.set(0, 2, 4)
    solved = solve(board)
    assert solved is not None
    assert solved.get(0, 2) == 4
    assert not solved.is_given(0, 2)
    assert solved.to_string() == SOLUTION


# ---------- 6. 世界最難數獨 ----------


def test_solve_worlds_hardest_sudoku() -> None:
    board = Board.from_string(HARDEST)
    start = time.perf_counter()
    solved = solve(board)
    elapsed = time.perf_counter() - start
    assert solved is not None
    assert_valid_solution(solved, board)
    assert elapsed < HARDEST_TIME_LIMIT_SECONDS, f"解題耗時 {elapsed:.3f} 秒"


def test_worlds_hardest_has_unique_solution() -> None:
    assert count_solutions(Board.from_string(HARDEST), limit=2) == 1


# ---------- 7. 無解盤面 ----------


def test_solve_conflicting_board_returns_none() -> None:
    board = Board.from_string(EMPTY_STRING)
    board.set(0, 0, 5)
    board.set(0, 1, 5)
    assert solve(board) is None
    assert count_solutions(board) == 0


def test_solve_unsolvable_without_conflict_returns_none() -> None:
    # 第 0 行填 1–8，(0,8) 只能填 9，但 (1,8) 已有 9 → 無衝突卻無解
    board = Board.from_string("123456780" + "000000009" + "0" * 63)
    assert board.conflicts() == set()
    assert solve(board) is None
    assert count_solutions(board) == 0


def test_solve_full_but_invalid_board_returns_none() -> None:
    invalid = "1" + SOLUTION[1:-1] + "1"
    board = Board.from_string(invalid)
    assert board.conflicts() != set()
    assert solve(board) is None
    assert count_solutions(board, limit=5) == 0


# ---------- 8. 多解與空盤 count_solutions ----------


def test_count_solutions_empty_board_is_two() -> None:
    assert count_solutions(Board.from_string(EMPTY_STRING), limit=2) == 2


def test_count_solutions_default_limit_is_two() -> None:
    assert count_solutions(Board.from_string(EMPTY_STRING)) == 2


def test_count_solutions_multi_solution_board() -> None:
    # 從唯一解挖掉一個「致命矩形」的 4 格（數字在 2 行 2 列 2 宮內兩兩互換）→ 恰好 2 解
    board = Board.from_string(SOLUTION)
    rectangle = _find_deadly_rectangle(board)
    assert rectangle is not None, "測試資料應存在致命矩形"
    for r, c in rectangle:
        board.set(r, c, 0)
    assert count_solutions(board, limit=2) == 2
    assert count_solutions(board, limit=10) == 2


def test_count_solutions_unique_puzzle_is_one() -> None:
    assert count_solutions(Board.from_string(PUZZLE), limit=2) == 1


def test_count_solutions_respects_limit() -> None:
    empty = Board.from_string(EMPTY_STRING)
    assert count_solutions(empty, limit=1) == 1
    assert count_solutions(empty, limit=5) == 5


@pytest.mark.parametrize("bad_limit", [0, -1])
def test_count_solutions_invalid_limit_raises(bad_limit: int) -> None:
    with pytest.raises(ValueError):
        count_solutions(Board.from_string(EMPTY_STRING), limit=bad_limit)


@pytest.mark.parametrize("bad_limit", [True, 2.0, "2", None])
def test_count_solutions_wrong_limit_type_raises_type_error(bad_limit: object) -> None:
    with pytest.raises(TypeError):
        count_solutions(Board.from_string(EMPTY_STRING), limit=bad_limit)  # type: ignore[arg-type]


def test_solve_empty_board_gives_valid_grid() -> None:
    board = Board.from_string(EMPTY_STRING)
    solved = solve(board)
    assert solved is not None
    assert_valid_solution(solved, board)


# ---------- 9. solve 不修改輸入盤面 ----------


def test_solve_does_not_modify_input() -> None:
    board = Board.from_string(HARDEST)
    before_grid = board.to_grid()
    before_given = board.given_grid()
    solved = solve(board)
    assert solved is not None
    assert solved is not board
    assert board.to_grid() == before_grid
    assert board.given_grid() == before_given
    # 修改回傳值也不能回頭影響輸入
    solved.set(0, 1, 0)
    assert board.to_grid() == before_grid


def test_count_solutions_does_not_modify_input() -> None:
    board = Board.from_string(PUZZLE)
    before = board.copy()
    count_solutions(board, limit=2)
    assert board == before


def test_failed_solve_does_not_modify_input() -> None:
    board = Board.from_string("123456780" + "000000009" + "0" * 63)
    before = board.copy()
    assert solve(board) is None
    assert board == before


# ---------- 輔助 ----------


def _find_deadly_rectangle(board: Board) -> list[tuple[int, int]] | None:
    """找一組 (r1,c1)(r1,c2)(r2,c1)(r2,c2)，兩數字對角互換後盤面仍合法。

    條件：a=board[r1][c1]=board[r2][c2]、b=board[r1][c2]=board[r2][c1]，
    且兩行同屬一個宮列帶，或兩列同屬一個宮行帶——如此四格只落在兩個宮內，
    互換後每行、每列、每宮的數字集合不變；挖掉後每行只缺 {a,b}，恰好 2 解。
    """
    for r1 in range(9):
        for r2 in range(r1 + 1, 9):
            for c1 in range(9):
                for c2 in range(c1 + 1, 9):
                    if r1 // 3 != r2 // 3 and c1 // 3 != c2 // 3:
                        continue
                    a = board.get(r1, c1)
                    b = board.get(r1, c2)
                    if board.get(r2, c2) == a and board.get(r2, c1) == b:
                        return [(r1, c1), (r1, c2), (r2, c1), (r2, c2)]
    return None
