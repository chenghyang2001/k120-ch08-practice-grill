"""數獨盤面資料結構。

座標一律 (row, col)，0-based，範圍 0–8；數值 1–9，0 表示空格。
本模組為純邏輯核心，不得 import tkinter。
"""

from __future__ import annotations

from typing import Self

Grid = tuple[tuple[int, ...], ...]  # 9×9 不可變，用於 Puzzle

SIZE = 9
BOX_SIZE = 3
EMPTY = 0
DIGITS: frozenset[int] = frozenset(range(1, SIZE + 1))
_EMPTY_CHARS = frozenset("0.")


def _validate_coord(row: int, col: int) -> None:
    """座標型別錯誤（非 int、bool）拋 TypeError；越界拋 ValueError。"""
    for name, index in (("row", row), ("col", col)):
        # bool 是 int 子類別，明確排除以免 True 被當成 1 悄悄通過
        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError(f"{name} 必須是整數，收到 {index!r}")
        if not 0 <= index < SIZE:
            raise ValueError(f"{name} 超出範圍 0–8：{index}")


def _validate_value(value: int) -> None:
    """數值型別錯誤（非 int、bool）拋 TypeError；不在 0–9 拋 ValueError。"""
    # bool 是 int 子類別，明確排除以免 True 被當成 1 悄悄通過
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"數值必須是整數，收到 {value!r}")
    if not 0 <= value <= SIZE:
        raise ValueError(f"數值超出範圍 0–9：{value}")


def _require_sequence(obj: object, label: str) -> None:
    """不是 list 或 tuple 時拋 TypeError。

    只接受 list/tuple 白名單：str、bytes 有 len() 卻會被逐字元誤解析，
    set、dict 有 len() 卻沒有固定順序，鴨子型別判斷會讓這些輸入悄悄通過。
    """
    if not isinstance(obj, (list, tuple)):
        raise TypeError(f"{label}必須是序列（list/tuple），收到 {type(obj).__name__}")


def _box_origin(row: int, col: int) -> tuple[int, int]:
    """回傳 (row, col) 所在 3×3 宮的左上角座標。"""
    return (row // BOX_SIZE) * BOX_SIZE, (col // BOX_SIZE) * BOX_SIZE


def _peers(row: int, col: int) -> set[tuple[int, int]]:
    """同行、同列、同宮的所有格子（不含自己）。"""
    peers: set[tuple[int, int]] = set()
    for i in range(SIZE):
        peers.add((row, i))
        peers.add((i, col))
    box_row, box_col = _box_origin(row, col)
    for r in range(box_row, box_row + BOX_SIZE):
        for c in range(box_col, box_col + BOX_SIZE):
            peers.add((r, c))
    peers.discard((row, col))
    return peers


def _all_units() -> list[list[tuple[int, int]]]:
    """回傳 27 個單位（9 行、9 列、9 宮）的座標清單。"""
    units: list[list[tuple[int, int]]] = []
    for i in range(SIZE):
        units.append([(i, c) for c in range(SIZE)])
        units.append([(r, i) for r in range(SIZE)])
    for box_row in range(0, SIZE, BOX_SIZE):
        for box_col in range(0, SIZE, BOX_SIZE):
            units.append(
                [
                    (r, c)
                    for r in range(box_row, box_row + BOX_SIZE)
                    for c in range(box_col, box_col + BOX_SIZE)
                ]
            )
    return units


# 單位與鄰格在模組載入時算一次即可，避免 conflicts()/candidates() 每次重算
UNITS: tuple[tuple[tuple[int, int], ...], ...] = tuple(tuple(u) for u in _all_units())
PEERS: dict[tuple[int, int], frozenset[tuple[int, int]]] = {
    (r, c): frozenset(_peers(r, c)) for r in range(SIZE) for c in range(SIZE)
}


class Board:
    """可變的 9×9 數獨盤面，另記錄每格是否為給定格（題目原有或提示鎖定）。

    `set()` 不檢查鎖定，鎖定規則由 game 模組負責，讓 solver 等核心能自由操作。
    """

    __slots__ = ("_cells", "_given")

    def __init__(self) -> None:
        """建立全空且無給定格的盤面。"""
        self._cells: list[list[int]] = [[EMPTY] * SIZE for _ in range(SIZE)]
        self._given: list[list[bool]] = [[False] * SIZE for _ in range(SIZE)]

    # ---------- 建構 ----------

    @classmethod
    def from_grid(cls, grid: Grid | list[list[int]]) -> Self:
        """由 9×9 巢狀序列建立盤面；非 0 的格子視為給定格。

        傳入字串或非序列、格子非 int → TypeError；
        形狀不是 9×9 或數值不在 0–9 → ValueError。
        """
        _require_sequence(grid, "盤面")
        if len(grid) != SIZE:
            raise ValueError(f"盤面必須有 {SIZE} 列，收到 {len(grid)}")
        board = cls()
        for r, row_values in enumerate(grid):
            _require_sequence(row_values, f"第 {r} 列")
            if len(row_values) != SIZE:
                raise ValueError(f"第 {r} 列必須有 {SIZE} 格，收到 {len(row_values)}")
            for c, value in enumerate(row_values):
                _validate_value(value)
                board._cells[r][c] = value
                board._given[r][c] = value != EMPTY
        return board

    @classmethod
    def from_string(cls, s: str) -> Self:
        """由 81 字元字串建立盤面；'0' 或 '.' 為空格，'1'–'9' 為給定格。

        非字串 → TypeError；長度不是 81 或含其他字元 → ValueError。
        """
        if not isinstance(s, str):
            raise TypeError(f"輸入必須是字串，收到 {type(s).__name__}")
        if len(s) != SIZE * SIZE:
            raise ValueError(f"字串長度必須為 81，收到 {len(s)}")
        values: list[int] = []
        for index, char in enumerate(s):
            if char in _EMPTY_CHARS:
                values.append(EMPTY)
            elif "1" <= char <= "9":
                values.append(int(char))
            else:
                raise ValueError(f"第 {index} 個字元非法：{char!r}")
        grid = [values[r * SIZE : (r + 1) * SIZE] for r in range(SIZE)]
        return cls.from_grid(grid)

    # ---------- 讀寫 ----------

    def get(self, row: int, col: int) -> int:
        """取得格子數值（0 表示空格）。"""
        _validate_coord(row, col)
        return self._cells[row][col]

    def set(self, row: int, col: int, value: int) -> None:
        """設定格子數值；不檢查給定格鎖定（由 game 負責）。"""
        _validate_coord(row, col)
        _validate_value(value)
        self._cells[row][col] = value

    def is_given(self, row: int, col: int) -> bool:
        """該格是否為給定格（題目原有或提示鎖定）。"""
        _validate_coord(row, col)
        return self._given[row][col]

    def lock(self, row: int, col: int) -> None:
        """將格子設為給定格；提示填入正解後呼叫，讓玩家無法再改。"""
        _validate_coord(row, col)
        self._given[row][col] = True

    # ---------- 規則查詢 ----------

    def candidates(self, row: int, col: int) -> set[int]:
        """回傳該格依同行/列/宮規則可填的數字集合。

        已填格也會計算：排除自己後，以同行列宮其他格已出現的數字做排除，
        因此結果可能包含（也可能不含）該格目前的值；GUI 或提示可藉此判斷
        已填值是否仍屬合法候選。
        """
        _validate_coord(row, col)
        used = {self._cells[r][c] for r, c in PEERS[(row, col)]}
        return set(DIGITS - used)

    def conflicts(self) -> set[tuple[int, int]]:
        """回傳所有參與規則重複的格子座標（空格不計）。"""
        conflicting: set[tuple[int, int]] = set()
        for unit in UNITS:
            positions_by_value: dict[int, list[tuple[int, int]]] = {}
            for r, c in unit:
                value = self._cells[r][c]
                if value != EMPTY:
                    positions_by_value.setdefault(value, []).append((r, c))
            for positions in positions_by_value.values():
                if len(positions) > 1:
                    conflicting.update(positions)
        return conflicting

    def is_full(self) -> bool:
        """是否已無空格（不判斷正確性）。"""
        return all(value != EMPTY for row_values in self._cells for value in row_values)

    # ---------- 轉換 ----------

    def to_grid(self) -> Grid:
        """輸出不可變的 9×9 tuple，供 Puzzle 儲存或比較。"""
        return tuple(tuple(row_values) for row_values in self._cells)

    def given_grid(self) -> tuple[tuple[bool, ...], ...]:
        """輸出不可變的給定格旗標，方便測試與比較。"""
        return tuple(tuple(row_flags) for row_flags in self._given)

    def to_string(self) -> str:
        """輸出 81 字元字串（空格以 '0' 表示），與 from_string 互為反函式。"""
        return "".join(str(value) for row_values in self._cells for value in row_values)

    def copy(self) -> Self:
        """深拷貝盤面與給定格旗標，修改副本不影響原盤。

        用 type(self)() 建立副本，子類別呼叫 copy() 時仍得到子類別實例。
        """
        clone = type(self)()
        clone._cells = [list(row_values) for row_values in self._cells]
        clone._given = [list(row_flags) for row_flags in self._given]
        return clone

    # ---------- 協定 ----------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Board):
            return NotImplemented
        return self._cells == other._cells and self._given == other._given

    # 盤面可變，不可作為 dict key
    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        # 不寫成 Board.from_string(...)：那樣無法重建給定格旗標（玩家填入或 lock 的格子），
        # 會誤導讀者以為 eval(repr) 能得到相等盤面
        given_count = sum(flag for row_flags in self._given for flag in row_flags)
        return f"<{type(self).__name__} {self.to_string()!r} givens={given_count}>"

    def __str__(self) -> str:
        lines: list[str] = []
        for r, row_values in enumerate(self._cells):
            if r and r % BOX_SIZE == 0:
                lines.append("------+-------+------")
            chunks = [
                " ".join(str(v) if v else "." for v in row_values[i : i + BOX_SIZE])
                for i in range(0, SIZE, BOX_SIZE)
            ]
            lines.append(" | ".join(chunks))
        return "\n".join(lines)
