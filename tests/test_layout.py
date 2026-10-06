"""gui/layout.py 純函式單元測試（spec §8 第 23 項＋§6 顏色規則）。

layout 不 import tkinter，本檔在沒有圖形環境的機器上也能跑。
"""

from __future__ import annotations

import ast
import math
import random
from pathlib import Path

import pytest

from sudoku.game import GameSession
from sudoku.generator import Difficulty, Puzzle
from sudoku.gui import layout
from sudoku.gui.layout import (
    BG_DEFAULT,
    BG_PEER,
    BG_SAME_VALUE,
    BG_SELECTED,
    BG_WRONG,
    CONFLICT_COLOR,
    GIVEN_COLOR,
    HINT_COLOR,
    PLAYER_COLOR,
    CellStyle,
    cell_style,
    cell_to_pixel,
    format_elapsed,
    format_puzzle_title,
    move_selection,
    pixel_to_cell,
)

CELL = 50
MARGIN = 10
BOARD_END = MARGIN + 9 * CELL  # 460：右/下邊界線，已在盤面外

GIVENS = "530070000600195000098000060800060003400803001700020006060000280000419005000080079"
SOLUTION = "534678912672195348198342567859761423426853791713924856961537284287419635345286179"
EMPTY_A = (0, 2)  # 正解 4
EMPTY_B = (0, 3)  # 正解 6
GIVEN_CELL = (0, 0)  # 給定 5


def to_grid(text: str) -> tuple[tuple[int, ...], ...]:
    values = [int(ch) for ch in text]
    return tuple(tuple(values[r * 9 : (r + 1) * 9]) for r in range(9))


def make_puzzle(difficulty: Difficulty = Difficulty.MEDIUM, seed: int = 0) -> Puzzle:
    grid = to_grid(GIVENS)
    return Puzzle(
        givens=grid,
        solution=to_grid(SOLUTION),
        difficulty=difficulty,
        clue_count=sum(1 for row in grid for v in row if v != 0),
        seed=seed,
    )


@pytest.fixture
def session() -> GameSession:
    return GameSession(make_puzzle(), rng=random.Random(1))


# ---------- 模組邊界 ----------


def _imported_modules(source: str) -> set[str]:
    """以 ast 列出原始碼中所有 import 的模組名稱（docstring、註解中的字樣不會誤判）。"""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_layout_does_not_import_tkinter() -> None:
    # spec 決策 2：只有 gui/app.py 可以 import tkinter
    source_path = layout.__file__
    assert source_path is not None
    source = Path(source_path).read_text(encoding="utf-8")
    modules = _imported_modules(source)
    assert not any(name == "tkinter" or name.startswith("tkinter.") for name in modules)
    # 反向確認掃描本身有效：layout 確實匯入了 sudoku.board
    assert "sudoku.board" in modules


def test_board_pixels_matches_geometry() -> None:
    assert layout.BOARD_PIXELS == 9 * layout.CELL_SIZE + 2 * layout.MARGIN


# ---------- pixel_to_cell ----------


@pytest.mark.parametrize(
    ("x", "y", "expected"),
    [
        (MARGIN + CELL // 2, MARGIN + CELL // 2, (0, 0)),  # 左上格中心
        (MARGIN + 4 * CELL + 25, MARGIN + 4 * CELL + 25, (4, 4)),  # 正中央格中心
        (BOARD_END - 1, BOARD_END - 1, (8, 8)),  # 右下格最後一個像素
        (MARGIN + 2 * CELL + 7, MARGIN + 6 * CELL + 40, (6, 2)),  # x 對應欄、y 對應列
    ],
)
def test_pixel_to_cell_inside(x: int, y: int, expected: tuple[int, int]) -> None:
    assert pixel_to_cell(x, y, CELL, MARGIN) == expected


@pytest.mark.parametrize(
    ("x", "y", "expected"),
    [
        (MARGIN, MARGIN, (0, 0)),  # 左/上邊界線屬於第 0 格
        (MARGIN + CELL, MARGIN, (0, 1)),  # 內部格線歸右側格
        (MARGIN, MARGIN + CELL, (1, 0)),  # 內部格線歸下側格
        (MARGIN + 3 * CELL, MARGIN + 3 * CELL, (3, 3)),  # 宮界粗線歸右下的宮
        (MARGIN + CELL - 1, MARGIN, (0, 0)),  # 格線前一像素仍屬左側格
    ],
)
def test_pixel_to_cell_on_grid_lines(x: int, y: int, expected: tuple[int, int]) -> None:
    assert pixel_to_cell(x, y, CELL, MARGIN) == expected


@pytest.mark.parametrize(
    ("x", "y"),
    [
        (MARGIN - 1, MARGIN + 5),  # 左邊外
        (MARGIN + 5, MARGIN - 1),  # 上邊外
        (BOARD_END, MARGIN + 5),  # 右邊界線（已在盤面外）
        (MARGIN + 5, BOARD_END),  # 下邊界線（已在盤面外）
        (BOARD_END + 100, BOARD_END + 100),  # 遠在右下
        (-1, -1),  # 負座標
        (-CELL, MARGIN + 5),  # 負一整格寬，不可被截斷誤判為第 0 欄
    ],
)
def test_pixel_to_cell_outside_returns_none(x: int, y: int) -> None:
    assert pixel_to_cell(x, y, CELL, MARGIN) is None


def test_pixel_to_cell_slightly_left_of_margin_is_outside() -> None:
    # int() 向零截斷會把 -0.5 格算成第 0 格；必須用地板除法
    assert pixel_to_cell(MARGIN - CELL / 2, MARGIN + 5, CELL, MARGIN) is None


def test_pixel_to_cell_zero_margin() -> None:
    assert pixel_to_cell(0, 0, CELL, 0) == (0, 0)
    assert pixel_to_cell(9 * CELL, 0, CELL, 0) is None


def test_pixel_to_cell_accepts_float() -> None:
    assert pixel_to_cell(MARGIN + 1.5 * CELL, MARGIN + 0.2, CELL, MARGIN) == (0, 1)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_pixel_to_cell_non_finite_is_outside(bad: float) -> None:
    assert pixel_to_cell(bad, MARGIN + 5, CELL, MARGIN) is None


@pytest.mark.parametrize("bad", ["10", None, True])
def test_pixel_to_cell_bad_coordinate_type_raises(bad: object) -> None:
    with pytest.raises(TypeError):
        pixel_to_cell(bad, 20, CELL, MARGIN)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("cell_size", "margin", "error"),
    [(0, 10, ValueError), (-5, 10, ValueError), (50, -1, ValueError), (50.0, 10, TypeError)],
)
def test_pixel_to_cell_bad_geometry_raises(
    cell_size: object, margin: object, error: type[Exception]
) -> None:
    with pytest.raises(error):
        pixel_to_cell(20, 20, cell_size, margin)  # type: ignore[arg-type]


# ---------- cell_to_pixel ----------


def test_cell_to_pixel_values() -> None:
    assert cell_to_pixel(0, 0, CELL, MARGIN) == (10, 10, 60, 60)
    assert cell_to_pixel(2, 5, CELL, MARGIN) == (260, 110, 310, 160)
    assert cell_to_pixel(8, 8, CELL, MARGIN) == (410, 410, BOARD_END, BOARD_END)


def test_cell_to_pixel_and_pixel_to_cell_are_inverse() -> None:
    for row in range(9):
        for col in range(9):
            x0, y0, x1, y1 = cell_to_pixel(row, col, CELL, MARGIN)
            assert pixel_to_cell(x0, y0, CELL, MARGIN) == (row, col)
            assert pixel_to_cell(x1 - 1, y1 - 1, CELL, MARGIN) == (row, col)
            assert pixel_to_cell((x0 + x1) / 2, (y0 + y1) / 2, CELL, MARGIN) == (row, col)


@pytest.mark.parametrize(("row", "col"), [(9, 0), (0, -1)])
def test_cell_to_pixel_out_of_range_raises(row: int, col: int) -> None:
    with pytest.raises(ValueError):
        cell_to_pixel(row, col, CELL, MARGIN)


# ---------- move_selection ----------


@pytest.mark.parametrize(
    ("start", "direction", "expected"),
    [
        ((4, 4), "Up", (3, 4)),
        ((4, 4), "Down", (5, 4)),
        ((4, 4), "Left", (4, 3)),
        ((4, 4), "Right", (4, 5)),
    ],
)
def test_move_selection_moves(
    start: tuple[int, int], direction: str, expected: tuple[int, int]
) -> None:
    assert move_selection(start, direction) == expected


@pytest.mark.parametrize(
    ("start", "direction"),
    [((0, 3), "Up"), ((8, 3), "Down"), ((3, 0), "Left"), ((3, 8), "Right")],
)
def test_move_selection_clamps_at_edges(start: tuple[int, int], direction: str) -> None:
    # 邊界夾住、不繞回對側
    assert move_selection(start, direction) == start


def test_move_selection_corner() -> None:
    assert move_selection((0, 0), "Up") == (0, 0)
    assert move_selection((0, 0), "Left") == (0, 0)
    assert move_selection((8, 8), "Down") == (8, 8)
    assert move_selection((8, 8), "Right") == (8, 8)


def test_move_selection_unknown_direction_raises() -> None:
    with pytest.raises(ValueError):
        move_selection((4, 4), "PageUp")


@pytest.mark.parametrize("bad", [[4, 4], (4,), None])
def test_move_selection_bad_selected_type_raises(bad: object) -> None:
    with pytest.raises(TypeError):
        move_selection(bad, "Up")  # type: ignore[arg-type]


def test_move_selection_out_of_range_selected_raises() -> None:
    with pytest.raises(ValueError):
        move_selection((9, 0), "Up")


# ---------- format_puzzle_title ----------


@pytest.mark.parametrize(
    ("difficulty", "seed", "expected"),
    [
        (Difficulty.HARD, 17, "困難 #17"),
        (Difficulty.EASY, 0, "簡單 #0"),
        (Difficulty.MEDIUM, 4294967295, "中等 #4294967295"),
    ],
)
def test_format_puzzle_title(difficulty: Difficulty, seed: int, expected: str) -> None:
    assert format_puzzle_title(make_puzzle(difficulty, seed)) == expected


def test_format_puzzle_title_rejects_non_puzzle() -> None:
    with pytest.raises(TypeError):
        format_puzzle_title("困難 #17")  # type: ignore[arg-type]


# ---------- format_elapsed ----------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00"),
        (59, "00:59"),
        (60, "01:00"),
        (3599, "59:59"),
        (3600, "1:00:00"),
        (3661, "1:01:01"),
        (36000, "10:00:00"),
        (59.9, "00:59"),  # 小數秒捨去
    ],
)
def test_format_elapsed(seconds: float, expected: str) -> None:
    assert format_elapsed(seconds) == expected


@pytest.mark.parametrize("bad", [-1, -0.5, math.nan, math.inf])
def test_format_elapsed_invalid_value_raises(bad: float) -> None:
    with pytest.raises(ValueError):
        format_elapsed(bad)


@pytest.mark.parametrize("bad", ["60", None, True])
def test_format_elapsed_invalid_type_raises(bad: object) -> None:
    with pytest.raises(TypeError):
        format_elapsed(bad)  # type: ignore[arg-type]


# ---------- cell_style：文字顏色 ----------


def test_cell_style_given_is_black_bold(session: GameSession) -> None:
    style = cell_style(session, *GIVEN_CELL)
    assert style == CellStyle(background=BG_DEFAULT, text_color=GIVEN_COLOR, bold=True)


def test_cell_style_hint_is_green_bold(session: GameSession) -> None:
    session.hint(*EMPTY_A)
    style = cell_style(session, *EMPTY_A)
    assert style.text_color == HINT_COLOR
    assert style.bold is True


def test_cell_style_player_is_blue_normal(session: GameSession) -> None:
    session.set_cell(*EMPTY_A, 4)
    style = cell_style(session, *EMPTY_A, conflicts=session.board.conflicts())
    assert style.text_color == PLAYER_COLOR
    assert style.bold is False


def test_cell_style_conflict_is_red(session: GameSession) -> None:
    session.set_cell(*EMPTY_A, 5)  # 與 (0,0) 給定 5 同列衝突
    conflicts = session.board.conflicts()
    player = cell_style(session, *EMPTY_A, conflicts=conflicts)
    given = cell_style(session, *GIVEN_CELL, conflicts=conflicts)
    assert player.text_color == CONFLICT_COLOR
    assert player.bold is False
    # 衝突的給定格也標紅，但保留粗體讓玩家分得出是題目原有的數字
    assert given.text_color == CONFLICT_COLOR
    assert given.bold is True


# ---------- cell_style：背景 ----------


def test_cell_style_wrong_cell_has_red_background(session: GameSession) -> None:
    session.set_cell(*EMPTY_A, 9)
    wrong = session.check()
    style = cell_style(session, *EMPTY_A, selected=EMPTY_A, wrong_cells=wrong)
    # 檢查錯格的紅底優先於選取高亮
    assert style.background == BG_WRONG


def test_cell_style_selection_highlights(session: GameSession) -> None:
    selected = (4, 4)
    assert cell_style(session, 4, 4, selected=selected).background == BG_SELECTED
    assert cell_style(session, 4, 0, selected=selected).background == BG_PEER  # 同列
    assert cell_style(session, 0, 4, selected=selected).background == BG_PEER  # 同欄
    assert cell_style(session, 3, 5, selected=selected).background == BG_PEER  # 同宮
    assert cell_style(session, 0, 0, selected=selected).background == BG_DEFAULT


def test_cell_style_same_value_highlight(session: GameSession) -> None:
    # 選取 (0,0) 的 5：盤面其他的 5 淡色高亮，即使不在同行列宮
    assert session.board.get(4, 4) == 0
    assert session.board.get(7, 8) == 5
    style = cell_style(session, 7, 8, selected=GIVEN_CELL)
    assert style.background == BG_SAME_VALUE


def test_cell_style_selected_empty_has_no_same_value_highlight(session: GameSession) -> None:
    # 選空格時不能把所有空格都當成「同數字」高亮
    style = cell_style(session, 8, 8, selected=EMPTY_B)
    assert style.background == BG_DEFAULT
    assert cell_style(session, 8, 0, selected=EMPTY_B).background == BG_DEFAULT


def test_cell_style_no_selection_default_background(session: GameSession) -> None:
    assert cell_style(session, 4, 4).background == BG_DEFAULT


def test_cell_style_out_of_range_raises(session: GameSession) -> None:
    with pytest.raises(ValueError):
        cell_style(session, 9, 0)
    with pytest.raises(ValueError):
        cell_style(session, 0, 0, selected=(0, 9))
