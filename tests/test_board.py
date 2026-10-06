"""board.py 單元測試（spec §8 第 1–4 項＋§7 邊界條件）。"""

from __future__ import annotations

import pytest

from sudoku.board import Board

# Wikipedia 範例題與其唯一解
PUZZLE = "530070000600195000098000060800060003400803001700020006060000280000419005000080079"
SOLUTION = "534678912672195348198342567859761423426853791713924856961537284287419635345286179"
EMPTY_STRING = "0" * 81


# ---------- 1. from_string / to_grid 往返一致 ----------


def test_from_string_to_grid_round_trip() -> None:
    board = Board.from_string(PUZZLE)
    grid = board.to_grid()
    rebuilt = "".join(str(v) for row in grid for v in row)
    assert rebuilt == PUZZLE
    assert Board.from_grid(grid) == board
    assert board.to_string() == PUZZLE


def test_from_string_accepts_dot_as_empty() -> None:
    dotted = PUZZLE.replace("0", ".")
    assert Board.from_string(dotted).to_grid() == Board.from_string(PUZZLE).to_grid()


def test_to_grid_is_immutable_nested_tuple() -> None:
    grid = Board.from_string(PUZZLE).to_grid()
    assert isinstance(grid, tuple)
    assert len(grid) == 9
    assert all(isinstance(row, tuple) and len(row) == 9 for row in grid)


def test_from_grid_accepts_list_and_marks_givens() -> None:
    grid = [[0] * 9 for _ in range(9)]
    grid[0][0] = 5
    grid[8][8] = 9
    board = Board.from_grid(grid)
    assert board.get(0, 0) == 5
    assert board.is_given(0, 0)
    assert board.is_given(8, 8)
    assert not board.is_given(4, 4)
    # 修改來源 list 不應影響已建立的盤面
    grid[0][0] = 1
    assert board.get(0, 0) == 5


def test_givens_follow_nonzero_cells_from_string() -> None:
    board = Board.from_string(PUZZLE)
    for r in range(9):
        for c in range(9):
            assert board.is_given(r, c) == (PUZZLE[r * 9 + c] != "0")


def test_set_does_not_change_given_flag_and_lock_works() -> None:
    board = Board.from_string(EMPTY_STRING)
    board.set(3, 4, 7)
    assert board.get(3, 4) == 7
    assert not board.is_given(3, 4)
    board.lock(3, 4)
    assert board.is_given(3, 4)
    # set 不檢查鎖定（由 game 負責）
    board.set(3, 4, 2)
    assert board.get(3, 4) == 2


def test_copy_is_independent() -> None:
    board = Board.from_string(PUZZLE)
    clone = board.copy()
    assert clone == board
    clone.set(0, 2, 4)
    clone.lock(0, 2)
    assert board.get(0, 2) == 0
    assert not board.is_given(0, 2)
    assert clone != board


def test_is_full() -> None:
    assert not Board.from_string(PUZZLE).is_full()
    assert Board.from_string(SOLUTION).is_full()
    assert not Board.from_string(EMPTY_STRING).is_full()


# ---------- 2. candidates 正確排除同行/列/宮 ----------


def test_candidates_excludes_row_col_box() -> None:
    board = Board.from_string(PUZZLE)
    # (0,2)：第 0 行有 5,3,7；第 2 列有 8；左上宮有 5,3,6,9,8
    assert board.candidates(0, 2) == {1, 2, 4}


def test_candidates_on_empty_board_is_all_digits() -> None:
    assert Board.from_string(EMPTY_STRING).candidates(4, 4) == set(range(1, 10))


def test_candidates_each_unit_separately() -> None:
    board = Board.from_string(EMPTY_STRING)
    board.set(0, 8, 1)  # 同行
    board.set(8, 0, 2)  # 同列
    board.set(1, 1, 3)  # 同宮
    board.set(5, 5, 4)  # 無關格
    assert board.candidates(0, 0) == {4, 5, 6, 7, 8, 9}


def test_candidates_on_filled_cell_excludes_self() -> None:
    board = Board.from_string(SOLUTION)
    # 已填格只排除鄰格數字，自身值仍是唯一合法候選
    assert board.candidates(0, 0) == {5}


def test_candidates_returns_independent_set() -> None:
    board = Board.from_string(EMPTY_STRING)
    result = board.candidates(0, 0)
    result.clear()
    assert board.candidates(0, 0) == set(range(1, 10))


# ---------- 3. conflicts 偵測行、列、宮重複 ----------


def test_conflicts_none_on_valid_boards() -> None:
    assert Board.from_string(PUZZLE).conflicts() == set()
    assert Board.from_string(SOLUTION).conflicts() == set()
    assert Board.from_string(EMPTY_STRING).conflicts() == set()


def test_conflicts_row_duplicate() -> None:
    board = Board.from_string(EMPTY_STRING)
    board.set(2, 0, 6)
    board.set(2, 8, 6)
    assert board.conflicts() == {(2, 0), (2, 8)}


def test_conflicts_col_duplicate() -> None:
    board = Board.from_string(EMPTY_STRING)
    board.set(0, 5, 3)
    board.set(7, 5, 3)
    assert board.conflicts() == {(0, 5), (7, 5)}


def test_conflicts_box_duplicate() -> None:
    board = Board.from_string(EMPTY_STRING)
    board.set(3, 3, 9)
    board.set(5, 5, 9)
    assert board.conflicts() == {(3, 3), (5, 5)}


def test_conflicts_collects_all_participants() -> None:
    board = Board.from_string(EMPTY_STRING)
    board.set(0, 0, 1)
    board.set(0, 4, 1)
    board.set(6, 0, 1)
    assert board.conflicts() == {(0, 0), (0, 4), (6, 0)}


def test_conflicts_ignores_empty_cells() -> None:
    board = Board.from_string(EMPTY_STRING)
    board.set(0, 0, 1)
    assert board.conflicts() == set()


# ---------- 4. 越界值與座標 → ValueError ----------


@pytest.mark.parametrize("value", [10, -1, 100])
def test_set_out_of_range_value_raises(value: int) -> None:
    board = Board.from_string(EMPTY_STRING)
    with pytest.raises(ValueError):
        board.set(0, 0, value)


@pytest.mark.parametrize(("row", "col"), [(-1, 0), (0, -1), (9, 0), (0, 9), (10, 10)])
def test_out_of_range_coordinates_raise(row: int, col: int) -> None:
    board = Board.from_string(EMPTY_STRING)
    with pytest.raises(ValueError):
        board.get(row, col)
    with pytest.raises(ValueError):
        board.set(row, col, 1)
    with pytest.raises(ValueError):
        board.is_given(row, col)
    with pytest.raises(ValueError):
        board.lock(row, col)
    with pytest.raises(ValueError):
        board.candidates(row, col)


@pytest.mark.parametrize("bad_value", [True, 1.0, "5", None])
def test_set_wrong_value_type_raises_type_error(bad_value: object) -> None:
    board = Board.from_string(EMPTY_STRING)
    with pytest.raises(TypeError):
        board.set(0, 0, bad_value)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_coord", [True, 1.0, "0", None])
def test_wrong_coordinate_type_raises_type_error(bad_coord: object) -> None:
    board = Board.from_string(EMPTY_STRING)
    with pytest.raises(TypeError):
        board.get(bad_coord, 0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        board.get(0, bad_coord)  # type: ignore[arg-type]


def test_from_grid_wrong_type_raises_type_error() -> None:
    with pytest.raises(TypeError):
        Board.from_grid("0" * 81)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Board.from_grid(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Board.from_grid(["000000000"] * 9)  # type: ignore[list-item]
    grid = [[0] * 9 for _ in range(9)]
    grid[0][0] = "5"  # type: ignore[call-overload]
    with pytest.raises(TypeError):
        Board.from_grid(grid)


def test_from_string_non_string_raises_type_error() -> None:
    with pytest.raises(TypeError):
        Board.from_string(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Board.from_string(123)  # type: ignore[arg-type]


def test_from_grid_out_of_range_value_raises() -> None:
    grid = [[0] * 9 for _ in range(9)]
    grid[4][4] = 10
    with pytest.raises(ValueError):
        Board.from_grid(grid)
    grid[4][4] = -1
    with pytest.raises(ValueError):
        Board.from_grid(grid)


@pytest.mark.parametrize(
    "bad_grid",
    [
        [[0] * 9 for _ in range(8)],
        [[0] * 8 for _ in range(9)],
        [],
    ],
)
def test_from_grid_wrong_shape_raises(bad_grid: list[list[int]]) -> None:
    with pytest.raises(ValueError):
        Board.from_grid(bad_grid)


@pytest.mark.parametrize(
    "bad_string",
    [
        "",
        "0" * 80,
        "0" * 82,
        "x" + "0" * 80,
        "0" * 80 + " ",
        "-" + "0" * 80,
    ],
)
def test_from_string_invalid_raises(bad_string: str) -> None:
    with pytest.raises(ValueError):
        Board.from_string(bad_string)
