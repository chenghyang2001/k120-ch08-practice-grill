"""gui/app.py 煙霧測試：建立真實 Tk 視窗（隱藏），直接呼叫 handler 模擬操作。

整個模組共用單一 Tk root（module scope），每個測試只在其下建立／銷毀 SudokuApp：
uv 預設的 CPython 3.12 + Tk 8.6 在同一行程反覆 Tk() 會出現「Can't find a usable tk.tcl」。
無法建立 Tk（沒有圖形顯示環境、或 Python 未附 Tcl/Tk）時整個模組 skip。
對話框換成不阻塞的替身，題目以注入的 puzzle_factory 提供固定題，測試不依賴出題器亂數。
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

tk = pytest.importorskip("tkinter")

from sudoku.game import GameSession, GameState  # noqa: E402
from sudoku.generator import Difficulty, Puzzle  # noqa: E402
from sudoku.gui.app import WINDOW_TITLE, SudokuApp  # noqa: E402
from sudoku.gui.layout import CELL_SIZE, MARGIN, cell_to_pixel  # noqa: E402

SOLUTION = "534678912672195348198342567859761423426853791713924856961537284287419635345286179"
EMPTY_A = (0, 2)  # 正解 4
EMPTY_B = (0, 3)  # 正解 6
GIVEN_CELL = (0, 0)
SEED = 17


def to_grid(text: str) -> tuple[tuple[int, ...], ...]:
    values = [int(ch) for ch in text]
    return tuple(tuple(values[r * 9 : (r + 1) * 9]) for r in range(9))


def near_solved_puzzle(difficulty: Difficulty) -> Puzzle:
    """只挖掉 A、B 兩格的題目，方便在測試中走到 SOLVED。"""
    chars = list(SOLUTION)
    for row, col in (EMPTY_A, EMPTY_B):
        chars[row * 9 + col] = "0"
    return Puzzle(
        givens=to_grid("".join(chars)),
        solution=to_grid(SOLUTION),
        difficulty=difficulty,
        clue_count=79,
        seed=SEED,
    )


class FakeDialogs:
    """記錄對話框呼叫、不阻塞；ask_yes_no 回傳 answer。"""

    def __init__(self) -> None:
        self.infos: list[tuple[str, str]] = []
        self.errors: list[tuple[str, str]] = []
        self.questions: list[tuple[str, str]] = []
        self.answer = True

    def show_info(self, title: str, message: str) -> None:
        self.infos.append((title, message))

    def show_error(self, title: str, message: str) -> None:
        self.errors.append((title, message))

    def ask_yes_no(self, title: str, message: str) -> bool:
        self.questions.append((title, message))
        return self.answer


class RecordingFactory:
    """記錄被要求的難度，回傳固定的近完成題。"""

    def __init__(self) -> None:
        self.requested: list[Difficulty] = []

    def __call__(self, difficulty: Difficulty) -> Puzzle:
        self.requested.append(difficulty)
        return near_solved_puzzle(difficulty)


@pytest.fixture(scope="module")
def root() -> Iterator[tk.Tk]:
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"無法建立 Tk 視窗：{exc}")
    window.withdraw()
    yield window
    # 視窗可能已被其他途徑關閉，再 destroy 會拋 TclError
    with contextlib.suppress(tk.TclError):
        window.destroy()


@pytest.fixture
def dialogs() -> FakeDialogs:
    return FakeDialogs()


@pytest.fixture
def factory() -> RecordingFactory:
    return RecordingFactory()


@pytest.fixture
def app(root: tk.Tk, dialogs: FakeDialogs, factory: RecordingFactory) -> Iterator[SudokuApp]:
    sudoku_app = SudokuApp(root, puzzle_factory=factory, dialogs=dialogs)
    yield sudoku_app
    # 只拆畫面、保留共用的 root，讓下一個測試在同一個 root 上重建
    sudoku_app.destroy()


def click(app: SudokuApp, cell: tuple[int, int]) -> None:
    x0, y0, x1, y1 = cell_to_pixel(*cell, CELL_SIZE, MARGIN)
    app.on_canvas_click(SimpleNamespace(x=(x0 + x1) // 2, y=(y0 + y1) // 2))  # type: ignore[arg-type]


def key(app: SudokuApp, keysym: str, char: str = "") -> None:
    app.on_key(SimpleNamespace(keysym=keysym, char=char))  # type: ignore[arg-type]


def current_session(app: SudokuApp) -> GameSession:
    session = app.session
    assert session is not None
    return session


# ---------- 啟動 ----------


def test_startup_opens_medium_game(app: SudokuApp, root: tk.Tk, factory: RecordingFactory) -> None:
    assert root.title() == WINDOW_TITLE
    assert factory.requested == [Difficulty.MEDIUM]
    assert app.title_text == f"中等 #{SEED}"
    assert app.timer_text == "00:00"
    assert current_session(app).state is GameState.PLAYING
    assert not app.is_control_enabled("undo")
    assert not app.is_control_enabled("redo")
    assert app.is_control_enabled("5")
    assert app.is_control_enabled("hint")


# ---------- 選格與填數 ----------


def test_click_fill_undo_redo(app: SudokuApp) -> None:
    click(app, EMPTY_A)
    assert app.selected == EMPTY_A
    app.on_digit(9)
    session = current_session(app)
    assert session.board.get(*EMPTY_A) == 9
    assert app.is_control_enabled("undo")
    app.on_undo()
    assert session.board.get(*EMPTY_A) == 0
    assert app.is_control_enabled("redo")
    app.on_redo()
    assert session.board.get(*EMPTY_A) == 9


def test_click_outside_board_keeps_selection(app: SudokuApp) -> None:
    click(app, EMPTY_A)
    app.on_canvas_click(SimpleNamespace(x=-5, y=-5))  # type: ignore[arg-type]
    assert app.selected == EMPTY_A


def test_digit_without_selection_shows_status(app: SudokuApp) -> None:
    app.on_digit(3)
    assert "選擇" in app.status_text
    assert not current_session(app).has_progress()


def test_keyboard_navigation_fill_and_clear(app: SudokuApp) -> None:
    key(app, "Right")  # 尚未選格：先選左上角
    assert app.selected == (0, 0)
    key(app, "Right")
    key(app, "Right")
    assert app.selected == EMPTY_A
    key(app, "7", "7")
    assert current_session(app).board.get(*EMPTY_A) == 7
    key(app, "BackSpace", "\b")
    assert current_session(app).board.get(*EMPTY_A) == 0
    key(app, "KP_8")  # NumLock 關閉時數字鍵盤只有 keysym
    assert current_session(app).board.get(*EMPTY_A) == 8
    key(app, "Delete")
    assert current_session(app).board.get(*EMPTY_A) == 0


def test_keyboard_ignores_other_keys(app: SudokuApp) -> None:
    click(app, EMPTY_A)
    key(app, "a", "a")
    key(app, "Shift_L")
    assert current_session(app).board.get(*EMPTY_A) == 0


def test_given_cell_cannot_be_changed(app: SudokuApp) -> None:
    click(app, GIVEN_CELL)
    app.on_digit(9)
    assert current_session(app).board.get(*GIVEN_CELL) == 5
    assert not app.is_control_enabled("undo")


# ---------- 檢查 ----------


def test_check_marks_wrong_cells_until_next_change(app: SudokuApp) -> None:
    click(app, EMPTY_A)
    app.on_digit(9)
    app.on_check()
    assert app.wrong_cells == {EMPTY_A}
    click(app, EMPTY_B)
    app.on_digit(1)  # 下一次修改盤面時清除紅底
    assert app.wrong_cells == frozenset()


# ---------- 結束 ----------


def test_solving_shows_message_and_locks_controls(app: SudokuApp, dialogs: FakeDialogs) -> None:
    click(app, EMPTY_A)
    app.on_digit(4)
    click(app, EMPTY_B)
    app.on_digit(6)
    assert current_session(app).state is GameState.SOLVED
    assert len(dialogs.infos) == 1
    assert "提示：0 次" in dialogs.infos[0][1]
    assert not app.is_control_enabled("5")
    assert not app.is_control_enabled("undo")
    assert not app.is_control_enabled("give_up")
    frozen = app.elapsed_seconds()
    assert app.elapsed_seconds() == frozen  # 停表後不再增加


def test_hint_then_solve_counts_hints(app: SudokuApp, dialogs: FakeDialogs) -> None:
    click(app, EMPTY_A)
    app.on_hint()
    session = current_session(app)
    assert session.hint_count == 1
    assert session.is_hinted(*EMPTY_A)
    app.on_hint()
    assert session.state is GameState.SOLVED
    assert "提示：2 次" in dialogs.infos[0][1]


def test_hint_digit_is_drawn_bold(app: SudokuApp) -> None:
    # spec §6／決策 15：提示格綠色粗體；從 Canvas 項目回查實際字型，而非只看 CellStyle
    click(app, EMPTY_A)
    app.on_digit(9)
    assert app.digit_font_weight(*EMPTY_A) == "normal"  # 玩家填的格子是一般字重
    app.on_hint()
    assert current_session(app).is_hinted(*EMPTY_A)
    assert app.digit_font_weight(*EMPTY_A) == "bold"
    assert app.digit_font_weight(*GIVEN_CELL) == "bold"
    assert app.digit_font_weight(*EMPTY_B) is None  # 空格沒有文字項目


def test_app_can_be_rebuilt_on_same_root(root: tk.Tk, dialogs: FakeDialogs) -> None:
    # 共用 root 的前提：destroy() 後同一 root 能再建新畫面，且舊畫面的按鍵綁定已解除
    first = SudokuApp(root, puzzle_factory=near_solved_puzzle, dialogs=dialogs)
    first.destroy()
    assert root.bind("<Key>") == ""
    second = SudokuApp(root, puzzle_factory=near_solved_puzzle, dialogs=dialogs)
    try:
        assert second.session is not None
        assert root.title() == WINDOW_TITLE
    finally:
        second.destroy()


def test_give_up_ends_without_dialog(app: SudokuApp, dialogs: FakeDialogs) -> None:
    app.on_give_up()
    assert current_session(app).state is GameState.GAVE_UP
    assert dialogs.infos == []
    assert "不計成績" in app.status_text
    assert not app.is_control_enabled("hint")


# ---------- 新遊戲 ----------


def test_new_game_without_progress_skips_confirmation(
    app: SudokuApp, dialogs: FakeDialogs, factory: RecordingFactory
) -> None:
    app.set_difficulty(Difficulty.HARD)
    app.on_new_game()
    assert dialogs.questions == []
    assert factory.requested[-1] is Difficulty.HARD
    assert app.title_text == f"困難 #{SEED}"


def test_new_game_with_progress_respects_cancel(
    app: SudokuApp, dialogs: FakeDialogs, factory: RecordingFactory
) -> None:
    click(app, EMPTY_A)
    app.on_digit(9)
    old_session = app.session
    dialogs.answer = False
    app.on_new_game()
    assert len(dialogs.questions) == 1
    assert app.session is old_session
    dialogs.answer = True
    app.on_new_game()
    assert app.session is not old_session
    assert len(factory.requested) == 2


def test_generation_failure_keeps_current_game(
    app: SudokuApp, dialogs: FakeDialogs, factory: RecordingFactory
) -> None:
    old_session = app.session

    def failing_factory(difficulty: Difficulty) -> Puzzle:
        raise RuntimeError("模擬出題失敗")

    app._puzzle_factory = failing_factory
    app.on_new_game()
    assert app.session is old_session
    assert len(dialogs.errors) == 1


# ---------- 非預期例外 ----------


def test_callback_exception_is_shown_in_dialog(
    app: SudokuApp, dialogs: FakeDialogs, capsys: pytest.CaptureFixture[str]
) -> None:
    error = ValueError("模擬錯誤")
    app._on_callback_error(ValueError, error, None)
    assert len(dialogs.errors) == 1
    assert "模擬錯誤" in dialogs.errors[0][1]
    assert "ValueError" in capsys.readouterr().err


def test_redraw_after_idle_does_not_raise(app: SudokuApp, root: tk.Tk) -> None:
    # 讓 Tk 真正處理一次待辦事件與重繪，確認 Canvas 繪製流程不會拋例外
    click(app, EMPTY_A)
    root.update_idletasks()
    root.update()
