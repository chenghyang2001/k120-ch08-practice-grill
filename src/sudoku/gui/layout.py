"""GUI 版面與顯示規則的純函式（spec §6）。

座標換算、選格移動、文字格式與顏色規則都抽成純函式，
讓這些規則不必開視窗就能單元測試；app.py 只負責把這裡算出的結果畫出來。
本模組不得 import tkinter。
"""

from __future__ import annotations

import math
from collections.abc import Set
from dataclasses import dataclass
from typing import Final, Protocol

from sudoku.board import BOX_SIZE, EMPTY, SIZE, validate_coord
from sudoku.game import BoardView
from sudoku.generator import Puzzle

Cell = tuple[int, int]

# 盤面幾何：52px 在 1080p 螢幕上數字清楚，整體 488px 也塞得進筆電小螢幕
CELL_SIZE: Final = 52
MARGIN: Final = 10
BOARD_PIXELS: Final = SIZE * CELL_SIZE + 2 * MARGIN

# 文字顏色（spec §6）：給定黑粗、提示綠粗、玩家藍、衝突紅
GIVEN_COLOR: Final = "#000000"
HINT_COLOR: Final = "#1b8a2f"
PLAYER_COLOR: Final = "#1f5fbf"
CONFLICT_COLOR: Final = "#d32f2f"

# 背景顏色：檢查錯格紅底最醒目，其次是選取格，再來同數字、同行列宮的淡色
BG_DEFAULT: Final = "#ffffff"
BG_SELECTED: Final = "#bbdefb"
BG_SAME_VALUE: Final = "#d0dff0"
BG_PEER: Final = "#eef3f8"
BG_WRONG: Final = "#ffcdd2"

# 方向鍵 keysym → (列位移, 欄位移)；直接用 tkinter 的 keysym 名稱，app 不必再轉換
DIRECTIONS: Final[dict[str, Cell]] = {
    "Up": (-1, 0),
    "Down": (1, 0),
    "Left": (0, -1),
    "Right": (0, 1),
}

_SECONDS_PER_HOUR: Final = 3600
_SECONDS_PER_MINUTE: Final = 60


class StyleSource(Protocol):
    """cell_style 需要的最小遊戲介面；GameSession 天然符合，測試也能用替身。"""

    @property
    def board(self) -> BoardView: ...

    def is_hinted(self, row: int, col: int) -> bool: ...


@dataclass(frozen=True)
class CellStyle:
    """一格的繪製樣式。"""

    background: str
    text_color: str
    bold: bool


# ---------- 座標換算 ----------


def _validate_geometry(cell_size: int, margin: int) -> None:
    """cell_size 必須是正整數、margin 必須是非負整數。

    bool 是 int 子類別，明確排除；cell_size 為 0 會在換算時除以零，提前擋下。
    """
    for name, value in (("cell_size", cell_size), ("margin", margin)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} 必須是整數，收到 {value!r}")
    if cell_size <= 0:
        raise ValueError(f"cell_size 必須大於 0，收到 {cell_size}")
    if margin < 0:
        raise ValueError(f"margin 不可為負數，收到 {margin}")


def _axis_index(position: float, cell_size: int, margin: int, name: str) -> int | None:
    """單一軸的像素 → 格子索引；盤面外回傳 None。"""
    if isinstance(position, bool) or not isinstance(position, (int, float)):
        raise TypeError(f"{name} 必須是數字，收到 {position!r}")
    if not math.isfinite(position):
        return None
    # 用地板除法而非 int()：int() 向零截斷，會把 margin 左側 -0.5 格誤判成第 0 格
    index = int((position - margin) // cell_size)
    return index if 0 <= index < SIZE else None


def pixel_to_cell(x: float, y: float, cell_size: int, margin: int) -> Cell | None:
    """Canvas 像素座標 → (row, col)；盤面外（含負座標）回傳 None。

    格線歸屬規則：每格在兩軸上各佔半開區間 [margin + k*cell_size, margin + (k+1)*cell_size)。
    因此：
    - 內部格線（含宮界粗線）上的像素歸給線「右側／下側」的格子
    - 盤面左／上邊界線（x 或 y == margin）屬於第 0 欄／列
    - 盤面右／下邊界線（x 或 y == margin + 9*cell_size）已在盤面外 → None
    NaN 或無限大視為盤面外。

    x、y 不是數字 → TypeError；cell_size、margin 型別錯 → TypeError，值不合法 → ValueError。
    """
    _validate_geometry(cell_size, margin)
    col = _axis_index(x, cell_size, margin, "x")
    row = _axis_index(y, cell_size, margin, "y")
    if row is None or col is None:
        return None
    return row, col


def cell_to_pixel(row: int, col: int, cell_size: int, margin: int) -> tuple[int, int, int, int]:
    """(row, col) → 格子矩形 (x0, y0, x1, y1)。

    x1、y1 與 pixel_to_cell 的半開區間一致：屬於下一格（或盤面外），
    所以 pixel_to_cell(x0, y0) 與 pixel_to_cell(x1 - 1, y1 - 1) 都會回到 (row, col)。
    座標型別錯誤 → TypeError；越界 → ValueError。
    """
    validate_coord(row, col)
    _validate_geometry(cell_size, margin)
    x0 = margin + col * cell_size
    y0 = margin + row * cell_size
    return x0, y0, x0 + cell_size, y0 + cell_size


def move_selection(selected: Cell, direction: str) -> Cell:
    """依方向鍵 keysym（Up/Down/Left/Right）移動選格，夾在 0–8 不越界、不繞回。

    selected 不是長度 2 的 tuple 或座標型別錯 → TypeError；
    座標越界或方向不認得 → ValueError。
    """
    if not isinstance(selected, tuple) or len(selected) != 2:
        raise TypeError(f"selected 必須是 (row, col) tuple，收到 {selected!r}")
    row, col = selected
    validate_coord(row, col)
    if direction not in DIRECTIONS:
        raise ValueError(f"不支援的方向：{direction!r}")
    delta_row, delta_col = DIRECTIONS[direction]
    new_row = min(max(row + delta_row, 0), SIZE - 1)
    new_col = min(max(col + delta_col, 0), SIZE - 1)
    return new_row, new_col


# ---------- 文字格式 ----------


def format_puzzle_title(puzzle: Puzzle) -> str:
    """題號標籤文字，例如「困難 #17」（spec 決策 14：題號與難度綁定，兩者一起顯示）。"""
    if not isinstance(puzzle, Puzzle):
        raise TypeError(f"puzzle 必須是 Puzzle，收到 {type(puzzle).__name__}")
    return f"{puzzle.difficulty.label} #{puzzle.seed}"


def format_elapsed(seconds: float) -> str:
    """經過秒數 → 「MM:SS」；滿 1 小時改為「H:MM:SS」。

    小數秒無條件捨去：計時標籤每秒更新，進位會讓剛開局就顯示 00:01。
    非數字或 bool → TypeError；負數、NaN、無限大 → ValueError。
    """
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise TypeError(f"seconds 必須是數字，收到 {seconds!r}")
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f"seconds 必須是非負有限數，收到 {seconds}")
    total = int(seconds)
    hours, remainder = divmod(total, _SECONDS_PER_HOUR)
    minutes, secs = divmod(remainder, _SECONDS_PER_MINUTE)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


# ---------- 顏色規則 ----------


def _is_peer(cell: Cell, other: Cell) -> bool:
    """兩格是否同行、同列或同宮（不含同一格）。"""
    if cell == other:
        return False
    same_box = (cell[0] // BOX_SIZE, cell[1] // BOX_SIZE) == (
        other[0] // BOX_SIZE,
        other[1] // BOX_SIZE,
    )
    return cell[0] == other[0] or cell[1] == other[1] or same_box


def _text_style(source: StyleSource, cell: Cell, conflicts: Set[Cell]) -> tuple[str, bool]:
    """文字顏色與是否粗體。

    提示格同時也是鎖定的給定格，必須先判斷提示，否則會被當成題目原有的黑字。
    衝突時只換顏色、保留粗體，讓玩家仍分得出哪個是題目原有的數字。
    """
    if source.is_hinted(*cell):
        color, bold = HINT_COLOR, True
    elif source.board.is_given(*cell):
        color, bold = GIVEN_COLOR, True
    else:
        color, bold = PLAYER_COLOR, False
    if cell in conflicts:
        color = CONFLICT_COLOR
    return color, bold


def _background(board: BoardView, cell: Cell, selected: Cell | None, wrong_cells: Set[Cell]) -> str:
    """背景顏色，依優先序：檢查錯格 > 選取格 > 同數字 > 同行列宮 > 預設。"""
    if cell in wrong_cells:
        return BG_WRONG
    if selected is None:
        return BG_DEFAULT
    if cell == selected:
        return BG_SELECTED
    selected_value = board.get(*selected)
    if selected_value != EMPTY and board.get(*cell) == selected_value:
        return BG_SAME_VALUE
    if _is_peer(cell, selected):
        return BG_PEER
    return BG_DEFAULT


def cell_style(
    source: StyleSource,
    row: int,
    col: int,
    *,
    selected: Cell | None = None,
    conflicts: Set[Cell] = frozenset(),
    wrong_cells: Set[Cell] = frozenset(),
) -> CellStyle:
    """決定一格的背景、文字顏色與粗細（spec §6 顏色規則）。

    conflicts 由呼叫端先算好一次再傳入：重繪 81 格時若每格各算一次 board.conflicts()
    會重複掃描 27 個單位 81 次。wrong_cells 是「檢查」按鈕的結果。
    座標型別錯誤 → TypeError；越界 → ValueError。
    """
    validate_coord(row, col)
    if selected is not None:
        validate_coord(*selected)
    cell = (row, col)
    text_color, bold = _text_style(source, cell, conflicts)
    background = _background(source.board, cell, selected, wrong_cells)
    return CellStyle(background=background, text_color=text_color, bold=bold)
