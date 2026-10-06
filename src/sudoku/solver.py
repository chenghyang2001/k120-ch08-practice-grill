"""數獨解題器：回溯＋候選數＋MRV（每次挑候選最少的空格）。

內部以 81 格扁平 list 與行/列/宮 bitmask 表示，避免每步重建 set，
讓「世界最難數獨」這類題目也能在 1 秒內解完。
本模組不得 import tkinter，也不修改傳入的 Board。

另提供模組內部函式 `_random_fill(rng)` 給 generator 產生隨機完整解，
與 solve / count_solutions 共用同一套回溯，避免 generator 另寫一套搜尋。
"""

from __future__ import annotations

import random
from collections.abc import Iterator

from sudoku.board import BOX_SIZE, EMPTY, SIZE, Board, Grid

_CELL_COUNT = SIZE * SIZE
# bit d（1 << d，d=1..9）代表數字 d；bit 0 不使用，讓數字可直接當位移量
_ALL_DIGITS_MASK = sum(1 << d for d in range(1, SIZE + 1))
_BOX_OF: tuple[int, ...] = tuple(
    (i // SIZE // BOX_SIZE) * BOX_SIZE + (i % SIZE) // BOX_SIZE for i in range(_CELL_COUNT)
)


class _SearchState:
    """回溯搜尋用的可變內部狀態（僅本模組使用）。"""

    __slots__ = ("box_masks", "cells", "col_masks", "row_masks")

    def __init__(self, cells: list[int]) -> None:
        self.cells = cells
        self.row_masks = [0] * SIZE
        self.col_masks = [0] * SIZE
        self.box_masks = [0] * SIZE

    def place(self, index: int, digit: int) -> None:
        bit = 1 << digit
        self.cells[index] = digit
        self.row_masks[index // SIZE] |= bit
        self.col_masks[index % SIZE] |= bit
        self.box_masks[_BOX_OF[index]] |= bit

    def remove(self, index: int, digit: int) -> None:
        bit = ~(1 << digit)
        self.cells[index] = EMPTY
        self.row_masks[index // SIZE] &= bit
        self.col_masks[index % SIZE] &= bit
        self.box_masks[_BOX_OF[index]] &= bit

    def allowed_mask(self, index: int) -> int:
        used = (
            self.row_masks[index // SIZE]
            | self.col_masks[index % SIZE]
            | self.box_masks[_BOX_OF[index]]
        )
        return _ALL_DIGITS_MASK & ~used


def _build_state(board: Board) -> _SearchState | None:
    """把 Board 轉成搜尋狀態；盤面本身已有重複則回傳 None。

    在放入時順便檢查 bitmask 是否已占用，等同 conflicts() 但只需一次掃描。
    """
    grid = board.to_grid()
    state = _SearchState([EMPTY] * _CELL_COUNT)
    for r in range(SIZE):
        for c in range(SIZE):
            digit = grid[r][c]
            if digit == EMPTY:
                continue
            index = r * SIZE + c
            if not state.allowed_mask(index) & (1 << digit):
                return None
            state.place(index, digit)
    return state


def _pick_mrv_cell(state: _SearchState, empties: list[int]) -> tuple[int, int]:
    """挑候選數最少的空格（MRV），回傳 (index, 候選 mask)；index=-1 表示已填滿。

    遇到 0 個候選可立即回傳，讓呼叫端馬上回溯，不必再掃描其餘格子。
    """
    best_index = -1
    best_mask = 0
    best_count = SIZE + 1
    for index in empties:
        if state.cells[index] != EMPTY:
            continue
        mask = state.allowed_mask(index)
        count = mask.bit_count()
        if count < best_count:
            best_index, best_mask, best_count = index, mask, count
            if count <= 1:
                break
    return best_index, best_mask


def _mask_digits(mask: int) -> list[int]:
    """把候選 bitmask 轉成由小到大的數字清單。"""
    digits: list[int] = []
    while mask:
        lowest_bit = mask & -mask
        mask ^= lowest_bit
        digits.append(lowest_bit.bit_length() - 1)
    return digits


def _search(
    state: _SearchState,
    empties: list[int],
    rng: random.Random | None = None,
) -> Iterator[list[int]]:
    """深度優先回溯，依序產生每個完整解（81 格扁平 list 的副本）。

    用 generator 讓 solve 取第一個解、count_solutions 數到 limit 就停，共用同一套搜尋。
    遞迴深度最多為空格數（≤ 81），不會觸及 Python 遞迴上限。

    rng 為 None 時候選由小到大嘗試，維持 solve / count_solutions 的決定性；
    有 rng 時打亂候選順序，讓 _random_fill 能由同一套搜尋產生隨機盤面。
    """
    index, mask = _pick_mrv_cell(state, empties)
    if index == -1:
        yield list(state.cells)
        return
    digits = _mask_digits(mask)
    if rng is not None:
        rng.shuffle(digits)
    for digit in digits:
        state.place(index, digit)
        yield from _search(state, empties, rng)
        state.remove(index, digit)


def _iter_solutions(board: Board) -> Iterator[list[int]]:
    """對 Board 產生所有解；有衝突時不產生任何解。"""
    state = _build_state(board)
    if state is None:
        return iter(())
    empties = [i for i, value in enumerate(state.cells) if value == EMPTY]
    return _search(state, empties)


def solve(board: Board) -> Board | None:
    """解出盤面並回傳新的 Board；無解或輸入已有衝突回傳 None。

    回傳盤面保留原本的給定格旗標，解出來填入的格子不是給定格；輸入盤面不被修改。
    """
    first_solution = next(_iter_solutions(board), None)
    if first_solution is None:
        return None
    solved = board.copy()
    for index, digit in enumerate(first_solution):
        row, col = divmod(index, SIZE)
        if solved.get(row, col) == EMPTY:
            solved.set(row, col, digit)
    return solved


def count_solutions(board: Board, limit: int = 2) -> int:
    """計算解的數量，數到 limit 即停（出題時只需知道「是否唯一」）。

    輸入已有衝突回傳 0。limit 非 int（含 bool）→ TypeError；limit < 1 → ValueError。
    """
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError(f"limit 必須是整數，收到 {limit!r}")
    if limit < 1:
        raise ValueError(f"limit 必須是正整數，收到 {limit}")
    found = 0
    for _ in _iter_solutions(board):
        found += 1
        if found >= limit:
            break
    return found


def _random_fill(rng: random.Random) -> Grid:
    """從空盤以隨機候選順序回溯，產生一個隨機的合法完整解（generator 專用）。

    只使用傳入的 rng，不碰全域 random 狀態，確保相同 seed 產生相同盤面。
    空盤必定有解，因此取不到解代表搜尋本身壞掉，以 RuntimeError 明確揭露。
    """
    if not isinstance(rng, random.Random):
        raise TypeError(f"rng 必須是 random.Random，收到 {type(rng).__name__}")
    state = _SearchState([EMPTY] * _CELL_COUNT)
    empties = list(range(_CELL_COUNT))
    flat_solution = next(_search(state, empties, rng), None)
    if flat_solution is None:
        raise RuntimeError("空盤找不到完整解，解題器狀態異常")
    return tuple(tuple(flat_solution[r * SIZE : (r + 1) * SIZE]) for r in range(SIZE))
