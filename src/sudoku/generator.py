"""數獨出題器：產生保證唯一解的題目，並依提示數評定難度。

出題流程（spec §4.3）：
1. 以「難度名稱:seed」建立專屬 rng（決策 14：題號與難度綁定），用 solver._random_fill 產生隨機完整解
2. 隨機順序逐格挖洞，每挖一格用 count_solutions(limit=2) 驗證唯一解，否則填回
3. 提示數降到目標值（在難度區間內隨機取）即停
4. 未進入區間就換新完整盤面重試，最多 MAX_RETRIES 次；仍失敗則取提示數最少的結果

整個流程只用以 seed 建立的 rng，不碰全域 random 狀態，確保相同 seed 產生相同題目。
重現性範圍：同一 seed 只保證在同一 Python 大版本、同一版 generator 演算法下重現同一題；
random.Random 的序列演算法或本模組挖洞流程一改，同一題號就可能對應到不同題目。
本模組不得 import tkinter，也不自行實作回溯（一律透過 solver）。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

from sudoku.board import EMPTY, SIZE, Board, Grid
from sudoku.solver import _random_fill, count_solutions

# 困難題單次挖洞偶爾停在區間上限之上，20 次重試在 1 秒預算內足以命中（spec 決策 9）
MAX_RETRIES = 20
# 合法題號範圍 0 <= seed < SEED_SPACE；上限讓 GUI 顯示的題號長度有界，
# seed=None 時也從此範圍挑題號
SEED_SPACE = 2**32


class Difficulty(Enum):
    """難度等級；顯示名稱由 label 取得，提示數區間由 clue_range 取得。"""

    EASY = "簡單"
    MEDIUM = "中等"
    HARD = "困難"

    @property
    def clue_range(self) -> tuple[int, int]:
        """此難度的提示數區間 (下限, 上限)，兩端皆含。"""
        return _CLUE_RANGES[self]

    @property
    def label(self) -> str:
        """顯示用中文名稱。

        GUI 一律透過 label 取名稱、不直接讀 value：日後若 value 改成英文代碼
        （例如為了序列化），顯示文字不必跟著改。
        """
        return self.value


# 放在類別外：Enum 類別內的 dict 屬性會被當成成員，無法當查表常數
_CLUE_RANGES: dict[Difficulty, tuple[int, int]] = {
    Difficulty.EASY: (36, 40),
    Difficulty.MEDIUM: (30, 35),
    Difficulty.HARD: (25, 29),
}


@dataclass(frozen=True)
class Puzzle:
    """一道題目；givens 與 solution 皆為不可變 Grid，game 端以 Board.from_grid 重建。

    difficulty 存玩家所選難度；clue_count 為實際提示數，
    可能因重試仍失敗、退而求其次而超出該難度區間。
    """

    givens: Grid
    solution: Grid
    difficulty: Difficulty
    clue_count: int
    seed: int


def _validate_difficulty(difficulty: object) -> None:
    """difficulty 不是 Difficulty 成員時拋 TypeError（例如傳入中文字串）。"""
    if not isinstance(difficulty, Difficulty):
        raise TypeError(f"difficulty 必須是 Difficulty，收到 {difficulty!r}")


def _validate_seed(seed: object) -> None:
    """seed 必須是 0 <= seed < SEED_SPACE 的整數。

    bool 是 int 子類別，明確排除以免 True 被當成 1；
    負數會被 random.Random 取絕對值，導致 -5 與 5 出同一題卻顯示不同題號，故拒絕；
    超過上限的巨大整數在 GUI 題號欄無法完整顯示，也不在 seed=None 會挑到的範圍內，一併拒絕。
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError(f"seed 必須是整數或 None，收到 {seed!r}")
    if not 0 <= seed < SEED_SPACE:
        raise ValueError(f"seed 必須在 0 <= seed < {SEED_SPACE} 範圍內，收到 {seed}")


def _make_rng(difficulty: Difficulty, seed: int) -> random.Random:
    """以「難度名稱:seed」字串建立出題 rng（spec 決策 14）。

    若只用 seed，「簡單 #17」與「困難 #17」會共用同一個完整解，只差挖洞多寡，
    玩家換難度後會覺得是同一題；把難度併入種子讓題號只在同難度內有意義。
    用 name（EASY）而非 label（簡單）：顯示文字日後可改，不應改變既有題號對應的題目。
    random.Random 對 str 種子以 SHA-512 雜湊，不受 PYTHONHASHSEED 影響，跨程序可重現。
    """
    return random.Random(f"{difficulty.name}:{seed}")


def _dig_holes(solution: Grid, target: int, rng: random.Random) -> tuple[Grid, int]:
    """從完整解隨機挖洞，保持唯一解，提示數降到 target 即停。

    回傳 (題目 Grid, 實際提示數)。若所有格子都試過仍高於 target，
    回傳當下（已無法再挖）的結果，由呼叫端決定是否重試。
    題目以 to_grid() 輸出：Board.set(r, c, 0) 不會清除給定旗標，
    不能把挖洞用的 Board 直接交給 game（spec §4.3 實作約束）。
    """
    board = Board.from_grid(solution)
    positions = [(row, col) for row in range(SIZE) for col in range(SIZE)]
    rng.shuffle(positions)
    clue_count = SIZE * SIZE
    for row, col in positions:
        if clue_count <= target:
            break
        original_value = board.get(row, col)
        board.set(row, col, EMPTY)
        if count_solutions(board, limit=2) == 1:
            clue_count -= 1
        else:
            board.set(row, col, original_value)
    return board.to_grid(), clue_count


def generate(difficulty: Difficulty, seed: int | None = None) -> Puzzle:
    """產生一道唯一解的題目。

    seed 為 None 時隨機取一個並存入 Puzzle.seed，讓 GUI 能顯示題號、日後重現同一題。
    題號與難度綁定：同一 seed 在不同難度下是不同的題目（spec 決策 14）。
    同一 seed 只保證在同一 Python 大版本、同一版 generator 演算法下重現同一題。
    重試 MAX_RETRIES 次仍未進入難度區間時不拋例外，回傳提示數最少的那次結果。

    difficulty 不是 Difficulty、seed 不是 int（或為 bool）→ TypeError；
    seed 不在 0 <= seed < SEED_SPACE → ValueError。
    """
    _validate_difficulty(difficulty)
    if seed is None:
        # 用 SystemRandom 挑題號：不讀也不推進全域 random 狀態，
        # 呼叫端（例如測試）先 random.seed() 過也不會讓每局題號都相同
        seed = random.SystemRandom().randrange(SEED_SPACE)
    else:
        _validate_seed(seed)
    rng = _make_rng(difficulty, seed)
    low, high = difficulty.clue_range

    best: tuple[Grid, Grid, int] | None = None
    for _ in range(MAX_RETRIES):
        solution = _random_fill(rng)
        target = rng.randint(low, high)
        givens, clue_count = _dig_holes(solution, target, rng)
        if best is None or clue_count < best[2]:
            best = (givens, solution, clue_count)
        # 挖洞在 target（≥ 下限）即停，因此只要不高於上限就已落在區間內
        if clue_count <= high:
            break

    if best is None:
        # 只有 MAX_RETRIES 被設成 < 1 時才會發生，屬於設定錯誤
        raise RuntimeError(f"MAX_RETRIES 必須至少為 1，目前為 {MAX_RETRIES}")
    givens, solution, clue_count = best
    return Puzzle(
        givens=givens,
        solution=solution,
        difficulty=difficulty,
        clue_count=clue_count,
        seed=seed,
    )


def rate_difficulty(givens: Grid) -> Difficulty:
    """依提示數（非 0 格數）評定難度（v1 不分析解題技巧）。

    區間：簡單 36–40、中等 30–35、困難 25–29。
    超出所有區間時歸到最近的一端：提示數 > 40 視為 EASY，< 25 視為 HARD，
    讓退而求其次的題目或玩家自訂盤面也一定能得到等級。

    givens 不是 list/tuple 或格子非 int → TypeError；形狀不是 9×9 或數值不在 0–9 → ValueError。
    """
    # 借 Board.from_grid 統一驗證形狀與數值，避免另寫一套檢查
    board = Board.from_grid(givens)
    clue_count = sum(
        1 for row in range(SIZE) for col in range(SIZE) if board.get(row, col) != EMPTY
    )
    if clue_count >= Difficulty.EASY.clue_range[0]:
        return Difficulty.EASY
    if clue_count >= Difficulty.MEDIUM.clue_range[0]:
        return Difficulty.MEDIUM
    return Difficulty.HARD
