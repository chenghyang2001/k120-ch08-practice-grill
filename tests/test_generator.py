"""generator.py 與 solver._random_fill 單元測試（spec §8 第 10–15 項＋§4.3 實作約束）。"""

from __future__ import annotations

import random
import time

import pytest

from sudoku import generator
from sudoku.board import Board, Grid
from sudoku.generator import (
    MAX_RETRIES,
    SEED_SPACE,
    Difficulty,
    Puzzle,
    generate,
    rate_difficulty,
)
from sudoku.solver import _random_fill, count_solutions, solve

SOLUTION = "534678912672195348198342567859761423426853791713924856961537284287419635345286179"
ALL_DIFFICULTIES = list(Difficulty)
SEEDS = [0, 1, 7, 42, 2024]
# 退而求其次時，提示數允許超出區間上限的容差（spec §8 第 12 項）
CLUE_TOLERANCE = 3
# spec 決策 9：困難題每題出題預算
HARD_TIME_LIMIT_SECONDS = 1.0
# 計時取多次最小值，排除 GC 或其他程序搶 CPU 造成的偶發尖峰（與 test_solver 一致）
TIMING_REPEATS = 3
DIGITS = set(range(1, 10))


def assert_valid_full_grid(grid: Grid) -> None:
    """完整解：9×9 tuple、每行列宮恰為 1–9。"""
    assert isinstance(grid, tuple)
    assert len(grid) == 9
    assert all(isinstance(row, tuple) and len(row) == 9 for row in grid)
    for i in range(9):
        assert set(grid[i]) == DIGITS
        assert {grid[r][i] for r in range(9)} == DIGITS
    for box_row in range(0, 9, 3):
        for box_col in range(0, 9, 3):
            box = {
                grid[r][c]
                for r in range(box_row, box_row + 3)
                for c in range(box_col, box_col + 3)
            }
            assert box == DIGITS


def count_clues(grid: Grid) -> int:
    return sum(1 for row in grid for value in row if value != 0)


def grid_with_clues(clue_count: int) -> Grid:
    """以已知完整解保留前 clue_count 格、其餘挖空，供 rate_difficulty 測試。"""
    values = [int(ch) for ch in SOLUTION]
    flat = [v if i < clue_count else 0 for i, v in enumerate(values)]
    return tuple(tuple(flat[r * 9 : (r + 1) * 9]) for r in range(9))


def expected_difficulty_for(clue_count: int) -> Difficulty:
    """依 spec 決策 4 的區間由提示數推難度（獨立於 rate_difficulty 的實作，供交叉比對）。"""
    if clue_count >= 36:
        return Difficulty.EASY
    if clue_count >= 30:
        return Difficulty.MEDIUM
    return Difficulty.HARD


# ---------- Difficulty ----------


def test_difficulty_values_are_chinese() -> None:
    assert Difficulty.EASY.value == "簡單"
    assert Difficulty.MEDIUM.value == "中等"
    assert Difficulty.HARD.value == "困難"


@pytest.mark.parametrize(
    ("difficulty", "expected_label"),
    [
        (Difficulty.EASY, "簡單"),
        (Difficulty.MEDIUM, "中等"),
        (Difficulty.HARD, "困難"),
    ],
)
def test_difficulty_label(difficulty: Difficulty, expected_label: str) -> None:
    assert difficulty.label == expected_label
    assert isinstance(difficulty.label, str)


def test_difficulty_clue_ranges() -> None:
    assert Difficulty.EASY.clue_range == (36, 40)
    assert Difficulty.MEDIUM.clue_range == (30, 35)
    assert Difficulty.HARD.clue_range == (25, 29)
    assert len(Difficulty) == 3


def test_max_retries_is_twenty() -> None:
    assert MAX_RETRIES == 20


def test_seed_space_is_two_to_the_32() -> None:
    assert SEED_SPACE == 2**32


# ---------- 10. 相同 seed 產生相同 Puzzle ----------


@pytest.mark.parametrize("difficulty", ALL_DIFFICULTIES)
def test_same_seed_same_puzzle(difficulty: Difficulty) -> None:
    first = generate(difficulty, seed=12345)
    second = generate(difficulty, seed=12345)
    assert first == second
    assert first.seed == 12345


def test_different_seeds_give_different_puzzles() -> None:
    puzzles = {generate(Difficulty.EASY, seed=seed).givens for seed in SEEDS}
    assert len(puzzles) == len(SEEDS)


@pytest.mark.parametrize("seed", [0, 17, 2024])
def test_same_seed_different_difficulty_gives_different_solution(seed: int) -> None:
    # spec 決策 14：題號與難度綁定，「簡單 #17」與「困難 #17」不可共用同一完整解
    solutions = {difficulty: generate(difficulty, seed=seed).solution for difficulty in Difficulty}
    assert len(set(solutions.values())) == len(Difficulty)


@pytest.mark.parametrize("difficulty", ALL_DIFFICULTIES)
def test_make_rng_uses_difficulty_name_and_seed(difficulty: Difficulty) -> None:
    # 種子格式固定為「難度名稱:seed」（用 name 不用 label，改顯示文字不影響題號對應）
    rng = generator._make_rng(difficulty, 17)
    expected = random.Random(f"{difficulty.name}:17")
    assert [rng.random() for _ in range(3)] == [expected.random() for _ in range(3)]


def test_generate_builds_rng_via_make_rng(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Difficulty, int]] = []
    original_make_rng = generator._make_rng

    def spying_make_rng(difficulty: Difficulty, seed: int) -> random.Random:
        calls.append((difficulty, seed))
        return original_make_rng(difficulty, seed)

    monkeypatch.setattr(generator, "_make_rng", spying_make_rng)
    generate(Difficulty.HARD, seed=17)
    assert calls == [(Difficulty.HARD, 17)]


def test_seed_none_records_reproducible_seed() -> None:
    puzzle = generate(Difficulty.MEDIUM)
    assert isinstance(puzzle.seed, int)
    assert not isinstance(puzzle.seed, bool)
    assert 0 <= puzzle.seed < SEED_SPACE
    assert generate(Difficulty.MEDIUM, seed=puzzle.seed) == puzzle


def test_generate_does_not_depend_on_global_random_state() -> None:
    random.seed(1)
    first = generate(Difficulty.HARD, seed=99)
    random.seed(2)
    random.random()
    second = generate(Difficulty.HARD, seed=99)
    assert first == second


@pytest.mark.parametrize("seed", [3, None])
def test_generate_does_not_consume_global_random(seed: int | None) -> None:
    # seed=None 改用 SystemRandom 挑題號，因此也不得推進全域 random 狀態
    random.seed(555)
    expected_next = random.random()
    random.seed(555)
    generate(Difficulty.EASY, seed=seed)
    assert random.random() == expected_next


def test_seed_none_ignores_global_random_seed() -> None:
    # 全域 random 被固定 seed 時，seed=None 仍應各自挑題號（SystemRandom 不受影響）
    seeds = set()
    for _ in range(3):
        random.seed(0)
        seeds.add(generate(Difficulty.EASY).seed)
    assert len(seeds) > 1


# ---------- 11. 三種難度：唯一解 ----------


@pytest.mark.parametrize("difficulty", ALL_DIFFICULTIES)
@pytest.mark.parametrize("seed", SEEDS)
def test_generated_puzzle_has_unique_solution(difficulty: Difficulty, seed: int) -> None:
    puzzle = generate(difficulty, seed=seed)
    assert count_solutions(Board.from_grid(puzzle.givens), limit=2) == 1


# ---------- 12. 提示數落在區間 ----------


@pytest.mark.parametrize("difficulty", ALL_DIFFICULTIES)
@pytest.mark.parametrize("seed", SEEDS)
def test_clue_count_within_range(difficulty: Difficulty, seed: int) -> None:
    puzzle = generate(difficulty, seed=seed)
    low, high = difficulty.clue_range
    assert puzzle.clue_count == count_clues(puzzle.givens)
    # 挖洞在目標值（≥ 下限）即停，不可能低於下限；退而求其次才可能略高於上限
    assert low <= puzzle.clue_count <= high + CLUE_TOLERANCE
    assert puzzle.difficulty is difficulty


# ---------- 13. solution 與 solve(givens) 一致 ----------


@pytest.mark.parametrize("difficulty", ALL_DIFFICULTIES)
@pytest.mark.parametrize("seed", SEEDS)
def test_solution_matches_solver(difficulty: Difficulty, seed: int) -> None:
    puzzle = generate(difficulty, seed=seed)
    solved = solve(Board.from_grid(puzzle.givens))
    assert solved is not None
    assert solved.to_grid() == puzzle.solution
    assert_valid_full_grid(puzzle.solution)


@pytest.mark.parametrize("difficulty", ALL_DIFFICULTIES)
def test_givens_match_solution_on_filled_cells(difficulty: Difficulty) -> None:
    puzzle = generate(difficulty, seed=8)
    for r in range(9):
        for c in range(9):
            value = puzzle.givens[r][c]
            if value != 0:
                assert value == puzzle.solution[r][c]


@pytest.mark.parametrize("difficulty", ALL_DIFFICULTIES)
def test_rebuilt_board_given_flags_follow_values(difficulty: Difficulty) -> None:
    # spec §4.3 實作約束：game 以 Board.from_grid(puzzle.givens) 重建，空格不可帶給定旗標
    puzzle = generate(difficulty, seed=21)
    board = Board.from_grid(puzzle.givens)
    for r in range(9):
        for c in range(9):
            assert board.is_given(r, c) == (puzzle.givens[r][c] != 0)


def test_puzzle_is_frozen_and_uses_immutable_grids() -> None:
    puzzle = generate(Difficulty.EASY, seed=5)
    assert isinstance(puzzle, Puzzle)
    assert isinstance(puzzle.givens, tuple)
    assert all(isinstance(row, tuple) for row in puzzle.givens)
    assert isinstance(puzzle.solution, tuple)
    with pytest.raises(AttributeError):
        puzzle.seed = 6  # type: ignore[misc]


# ---------- 重試與退而求其次 ----------


@pytest.mark.parametrize("seed", range(5))
def test_retry_stops_at_first_attempt_within_range(
    seed: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 不寫死「某 seed 第一次就命中」：決策 14 改了 rng 種子後舊 seed 的結果全變。
    # 改為記錄每次嘗試的提示數，斷言「第一次落在區間內就停」這條規則本身
    attempt_clues: list[int] = []
    original_dig = generator._dig_holes

    def recording_dig(solution: Grid, target: int, rng: random.Random) -> tuple[Grid, int]:
        givens, clue_count = original_dig(solution, target, rng)
        attempt_clues.append(clue_count)
        return givens, clue_count

    monkeypatch.setattr(generator, "_dig_holes", recording_dig)
    puzzle = generate(Difficulty.EASY, seed=seed)
    high = Difficulty.EASY.clue_range[1]
    assert all(clues > high for clues in attempt_clues[:-1])
    if attempt_clues[-1] <= high:
        assert puzzle.clue_count == attempt_clues[-1]
    else:
        assert len(attempt_clues) == MAX_RETRIES


def test_fallback_uses_fewest_clues_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    # 把困難區間改成不可能達成的 5–8，強迫每次都失敗以走退而求其次路徑
    monkeypatch.setitem(generator._CLUE_RANGES, Difficulty.HARD, (5, 8))
    monkeypatch.setattr(generator, "MAX_RETRIES", 3)
    attempt_clues: list[int] = []
    original_dig = generator._dig_holes

    def recording_dig(solution: Grid, target: int, rng: random.Random) -> tuple[Grid, int]:
        givens, clue_count = original_dig(solution, target, rng)
        attempt_clues.append(clue_count)
        return givens, clue_count

    monkeypatch.setattr(generator, "_dig_holes", recording_dig)
    puzzle = generate(Difficulty.HARD, seed=4)
    assert len(attempt_clues) == 3
    assert puzzle.clue_count == min(attempt_clues)
    assert puzzle.clue_count > 8
    assert puzzle.difficulty is Difficulty.HARD
    assert count_solutions(Board.from_grid(puzzle.givens), limit=2) == 1
    solved = solve(Board.from_grid(puzzle.givens))
    assert solved is not None
    assert solved.to_grid() == puzzle.solution


# ---------- 參數型別錯誤 ----------


@pytest.mark.parametrize("bad_difficulty", ["簡單", "EASY", None, 1, ("HARD",)])
def test_generate_invalid_difficulty_type_raises(bad_difficulty: object) -> None:
    with pytest.raises(TypeError):
        generate(bad_difficulty, seed=1)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_seed", [True, False, 1.0, "1", [1]])
def test_generate_invalid_seed_type_raises(bad_seed: object) -> None:
    with pytest.raises(TypeError):
        generate(Difficulty.EASY, seed=bad_seed)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_seed", [-1, SEED_SPACE, SEED_SPACE + 1, 2**64])
def test_generate_out_of_range_seed_raises_value_error(bad_seed: int) -> None:
    with pytest.raises(ValueError):
        generate(Difficulty.EASY, seed=bad_seed)


@pytest.mark.parametrize("edge_seed", [0, SEED_SPACE - 1])
def test_generate_accepts_seed_space_edges(edge_seed: int) -> None:
    puzzle = generate(Difficulty.EASY, seed=edge_seed)
    assert puzzle.seed == edge_seed


# ---------- 14. 效能：困難 × 20 seed，每題 < 1 秒 ----------


@pytest.mark.slow
@pytest.mark.parametrize("seed", range(20))
def test_hard_generation_within_time_budget(seed: int) -> None:
    timings: list[float] = []
    for _ in range(TIMING_REPEATS):
        start = time.perf_counter()
        puzzle = generate(Difficulty.HARD, seed=seed)
        timings.append(time.perf_counter() - start)
        assert puzzle.clue_count >= Difficulty.HARD.clue_range[0]
    best = min(timings)
    assert best < HARD_TIME_LIMIT_SECONDS, f"seed={seed} 出題最快耗時 {best:.3f} 秒"


# ---------- 15. rate_difficulty 邊界值 ----------


@pytest.mark.parametrize(
    ("clue_count", "expected"),
    [
        (25, Difficulty.HARD),
        (29, Difficulty.HARD),
        (30, Difficulty.MEDIUM),
        (35, Difficulty.MEDIUM),
        (36, Difficulty.EASY),
        (40, Difficulty.EASY),
    ],
)
def test_rate_difficulty_boundaries(clue_count: int, expected: Difficulty) -> None:
    assert rate_difficulty(grid_with_clues(clue_count)) is expected


@pytest.mark.parametrize(
    ("clue_count", "expected"),
    [
        (0, Difficulty.HARD),
        (17, Difficulty.HARD),
        (24, Difficulty.HARD),
        (41, Difficulty.EASY),
        (81, Difficulty.EASY),
    ],
)
def test_rate_difficulty_outside_ranges(clue_count: int, expected: Difficulty) -> None:
    assert rate_difficulty(grid_with_clues(clue_count)) is expected


def test_rate_difficulty_accepts_list_grid() -> None:
    grid = [list(row) for row in grid_with_clues(32)]
    assert rate_difficulty(grid) is Difficulty.MEDIUM  # type: ignore[arg-type]


@pytest.mark.parametrize("difficulty", ALL_DIFFICULTIES)
def test_rate_difficulty_matches_generated_puzzle(difficulty: Difficulty) -> None:
    # 掃描多個 seed 而非押單一 seed：任何一題都必須與「依 clue_count 推得的難度」一致，
    # 並要求至少一題真的落在所選難度區間，避免全部退而求其次時測試空跑通過
    low, high = difficulty.clue_range
    in_range_count = 0
    for seed in range(20):
        puzzle = generate(difficulty, seed=seed)
        assert rate_difficulty(puzzle.givens) is expected_difficulty_for(puzzle.clue_count)
        if low <= puzzle.clue_count <= high:
            in_range_count += 1
            assert rate_difficulty(puzzle.givens) is difficulty
    assert in_range_count >= 1, f"{difficulty.label} 掃描 20 個 seed 皆未落在區間"


@pytest.mark.parametrize("bad_givens", [None, "0" * 81, b"0" * 81, 81])
def test_rate_difficulty_invalid_type_raises(bad_givens: object) -> None:
    with pytest.raises(TypeError):
        rate_difficulty(bad_givens)  # type: ignore[arg-type]


def test_rate_difficulty_invalid_shape_raises() -> None:
    with pytest.raises(ValueError):
        rate_difficulty(((0,) * 9,) * 8)


# ---------- solver._random_fill ----------


@pytest.mark.parametrize("seed", SEEDS)
def test_random_fill_produces_valid_grid(seed: int) -> None:
    grid = _random_fill(random.Random(seed))
    assert_valid_full_grid(grid)
    assert Board.from_grid(grid).conflicts() == set()


def test_random_fill_same_seed_same_grid() -> None:
    assert _random_fill(random.Random(31)) == _random_fill(random.Random(31))


def test_random_fill_different_seeds_differ() -> None:
    grids = {_random_fill(random.Random(seed)) for seed in SEEDS}
    assert len(grids) == len(SEEDS)


def test_random_fill_rejects_non_rng() -> None:
    with pytest.raises(TypeError):
        _random_fill(42)  # type: ignore[arg-type]


def test_public_solver_stays_deterministic_after_random_fill() -> None:
    # _random_fill 打亂候選順序，不能影響 solve 對空盤的決定性結果
    empty = Board.from_string("0" * 81)
    before = solve(empty)
    _random_fill(random.Random(77))
    after = solve(empty)
    assert before is not None
    assert after is not None
    assert before == after
