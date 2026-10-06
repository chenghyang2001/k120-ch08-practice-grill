"""數獨 tkinter 視窗（spec §6）。

本專案唯一 import tkinter 的模組。所有改動盤面的操作只透過 GameSession，
顏色、座標換算、文字格式等規則交給 gui.layout 的純函式，這裡只負責接事件與繪製。
"""

from __future__ import annotations

import contextlib
import sys
import time
import tkinter as tk
import traceback
from collections.abc import Callable
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from types import TracebackType
from typing import Final, Protocol

from sudoku.board import BOX_SIZE, EMPTY, SIZE
from sudoku.game import GameSession, GameState
from sudoku.generator import Difficulty, Puzzle, generate
from sudoku.gui.layout import (
    BG_DEFAULT,
    BOARD_PIXELS,
    CELL_SIZE,
    DIRECTIONS,
    MARGIN,
    Cell,
    cell_style,
    cell_to_pixel,
    format_elapsed,
    format_puzzle_title,
    move_selection,
    pixel_to_cell,
)

WINDOW_TITLE: Final = "數獨"
# 系統沒有此字型時 tkinter 會自動 fallback，不需額外處理
FONT_FAMILY: Final = "Microsoft JhengHei"
UI_FONT: Final = (FONT_FAMILY, 11)
TIMER_FONT: Final = ("Consolas", 13)
# 盤面數字改用拉丁字型：JhengHei 的數字粗細兩種字重幾乎看不出差別，
# 提示格（綠粗）與玩家格（藍細）會分不清；Segoe UI 粗細差異明顯，不存在時 Tk 會 fallback
DIGIT_FONT_FAMILY: Final = "Segoe UI"
DIGIT_FONT_SIZE: Final = 20
DEFAULT_DIFFICULTY: Final = Difficulty.MEDIUM
TICK_MS: Final = 1000
THIN_LINE: Final = ("#9e9e9e", 1)
THICK_LINE: Final = ("#000000", 3)
CLEAR_KEYSYMS: Final = frozenset({"0", "KP_0", "Delete", "BackSpace"})
DIGIT_CHARS: Final = "123456789"
# 遊戲結束後要停用的控制項名稱；undo / redo 另依 can_undo / can_redo 決定
_PLAY_CONTROLS: Final = (*DIGIT_CHARS, "clear", "hint", "check", "give_up")

_UNDO_SEQUENCES: Final = ("<Control-z>", "<Control-Z>")
_REDO_SEQUENCES: Final = ("<Control-y>", "<Control-Y>")

PuzzleFactory = Callable[[Difficulty], Puzzle]


class Dialogs(Protocol):
    """對話框介面；抽出來讓煙霧測試能換成不會阻塞的替身。"""

    def show_info(self, title: str, message: str) -> None: ...

    def show_error(self, title: str, message: str) -> None: ...

    def ask_yes_no(self, title: str, message: str) -> bool: ...


class TkDialogs:
    """以 tkinter.messagebox 實作；指定 parent 讓對話框出現在主視窗上方。"""

    def __init__(self, parent: tk.Misc) -> None:
        self._parent = parent

    def show_info(self, title: str, message: str) -> None:
        messagebox.showinfo(title, message, parent=self._parent)

    def show_error(self, title: str, message: str) -> None:
        messagebox.showerror(title, message, parent=self._parent)

    def ask_yes_no(self, title: str, message: str) -> bool:
        return bool(messagebox.askyesno(title, message, parent=self._parent))


def _digit_tag(row: int, col: int) -> str:
    """盤面數字的 Canvas tag，讓測試與除錯能找回某格的文字項目。"""
    return f"digit-{row}-{col}"


def _digit_from_event(event: tk.Event) -> int | None:
    """從按鍵事件取出 1–9；數字鍵盤（KP_1…）在 NumLock 關閉時 char 為空，改看 keysym。"""
    char = getattr(event, "char", "")
    if len(char) == 1 and char in DIGIT_CHARS:
        return int(char)
    keysym = getattr(event, "keysym", "")
    if keysym.startswith("KP_") and keysym[3:] in tuple(DIGIT_CHARS):
        return int(keysym[3:])
    return None


class SudokuApp:
    """數獨主畫面：上方工具列、中央 Canvas 盤面、下方數字與功能按鈕。

    所有元件建在自己的容器 Frame 裡，掛在呼叫端傳入的 master 底下；
    destroy() 只拆掉這個容器，同一個 Tk root 可以反覆建立新的 SudokuApp
    （煙霧測試靠這點共用單一 root：部分 Python/Tk 組合反覆 Tk() 會找不到 tk.tcl）。
    puzzle_factory 與 dialogs 可注入，讓煙霧測試用固定題目與不阻塞的對話框替身。
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        puzzle_factory: PuzzleFactory = generate,
        dialogs: Dialogs | None = None,
        initial_difficulty: Difficulty = DEFAULT_DIFFICULTY,
    ) -> None:
        # 視窗層級設定（標題、按鍵、例外回報、游標）作用在 toplevel，元件則放進自己的容器
        self._root = master.winfo_toplevel()
        self._frame = ttk.Frame(master)
        self._frame.pack(fill="both", expand=True)
        self._puzzle_factory = puzzle_factory
        self._dialogs: Dialogs = dialogs if dialogs is not None else TkDialogs(self._root)
        self._session: GameSession | None = None
        self._selected: Cell | None = None
        self._wrong_cells: set[Cell] = set()
        self._end_announced = False
        self._start_time = time.monotonic()
        # 非 None 表示計時已停止（尚未開局或本局已結束），值為凍結的經過秒數
        self._stopped_elapsed: float | None = 0.0
        self._timer_job: str | None = None
        self._buttons: dict[str, ttk.Button] = {}
        self._difficulty_var = tk.StringVar(self._frame, value=initial_difficulty.label)
        self._title_var = tk.StringVar(self._frame, value="")
        self._timer_var = tk.StringVar(self._frame, value=format_elapsed(0))
        self._status_var = tk.StringVar(self._frame, value="")
        self._digit_fonts = self._create_digit_fonts()
        self._build_ui()
        self.start_game(initial_difficulty)

    def _create_digit_fonts(self) -> dict[bool, tkfont.Font]:
        """建立盤面數字的一般／粗體兩個具名字型，key 為 CellStyle.bold。

        各建一次並由 self 保留參考：Font 物件被回收時 Tk 端字型會被刪除；
        用具名字型而非 tuple，Canvas 項目才能以 itemcget 回查實際字重。
        """
        return {
            bold: tkfont.Font(
                root=self._root,
                family=DIGIT_FONT_FAMILY,
                size=DIGIT_FONT_SIZE,
                weight="bold" if bold else "normal",
            )
            for bold in (False, True)
        }

    # ---------- 唯讀狀態（供測試與外部查詢） ----------

    @property
    def session(self) -> GameSession | None:
        """目前這局；啟動時出題失敗則為 None。"""
        return self._session

    @property
    def selected(self) -> Cell | None:
        """目前選取的格子。"""
        return self._selected

    @property
    def wrong_cells(self) -> frozenset[Cell]:
        """「檢查」標出的錯格（下次修改盤面時清除）。"""
        return frozenset(self._wrong_cells)

    @property
    def title_text(self) -> str:
        return self._title_var.get()

    @property
    def timer_text(self) -> str:
        return self._timer_var.get()

    @property
    def status_text(self) -> str:
        return self._status_var.get()

    def is_control_enabled(self, name: str) -> bool:
        """控制項是否可按；name 為 "1"–"9"、clear、undo、redo、hint、check、give_up。"""
        return self._buttons[name].instate(["!disabled"])

    def elapsed_seconds(self) -> float:
        """本局經過秒數；結束後回傳凍結值。"""
        if self._stopped_elapsed is not None:
            return self._stopped_elapsed
        return time.monotonic() - self._start_time

    def digit_font_weight(self, row: int, col: int) -> str | None:
        """盤面上 (row, col) 數字實際使用的字重（"bold" / "normal"）；空格回傳 None。

        直接從 Canvas 項目回查字型，而非重算 CellStyle，才驗得到「真的畫成粗體」。
        """
        items = self._canvas.find_withtag(_digit_tag(row, col))
        if not items:
            return None
        font_name = self._canvas.itemcget(items[0], "font")
        return str(tkfont.nametofont(font_name, root=self._root).actual("weight"))

    def set_difficulty(self, difficulty: Difficulty) -> None:
        """設定下拉選單的難度；依 spec §5 不會立即重開，按「新遊戲」才生效。"""
        self._difficulty_var.set(difficulty.label)

    # ---------- 版面建構 ----------

    def _build_ui(self) -> None:
        self._configure_root()
        self._build_toolbar()
        self._build_canvas()
        self._build_digit_row()
        self._build_tool_row()
        self._build_status_bar()
        self._bind_keys()

    def _configure_root(self) -> None:
        self._root.title(WINDOW_TITLE)
        # 盤面以固定像素繪製，放大視窗只會多出空白，乾脆鎖定大小
        self._root.resizable(False, False)
        self._root.protocol("WM_DELETE_WINDOW", self.close)
        # 讓事件處理中的非預期例外以對話框呈現，而不是只在主控台默默印出
        self._root.report_callback_exception = self._on_callback_error  # type: ignore[method-assign]
        style = ttk.Style(self._root)
        style.configure("TButton", font=UI_FONT)
        style.configure("TLabel", font=UI_FONT)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self._frame, padding=(8, 8, 8, 0))
        bar.pack(fill="x")
        ttk.Label(bar, text="難度").pack(side="left")
        combo = ttk.Combobox(
            bar,
            textvariable=self._difficulty_var,
            values=[difficulty.label for difficulty in Difficulty],
            state="readonly",
            width=6,
            font=UI_FONT,
        )
        combo.pack(side="left", padx=(4, 8))
        # 選完難度把焦點還給盤面，否則方向鍵會被下拉選單吃掉而改到難度
        combo.bind("<<ComboboxSelected>>", lambda _event: self._canvas.focus_set())
        ttk.Button(bar, text="新遊戲", command=self.on_new_game).pack(side="left")
        ttk.Label(bar, textvariable=self._timer_var, font=TIMER_FONT).pack(side="right")
        ttk.Label(bar, textvariable=self._title_var).pack(side="right", padx=12)

    def _build_canvas(self) -> None:
        # highlightthickness=0：避免焦點框把繪圖原點往內推，讓 pixel_to_cell 的換算直接對應事件座標
        self._canvas = tk.Canvas(
            self._frame,
            width=BOARD_PIXELS,
            height=BOARD_PIXELS,
            background=BG_DEFAULT,
            highlightthickness=0,
        )
        self._canvas.pack(padx=8, pady=8)
        self._canvas.bind("<Button-1>", self.on_canvas_click)

    def _build_digit_row(self) -> None:
        row = ttk.Frame(self._frame, padding=(8, 0))
        row.pack()
        for value in range(1, SIZE + 1):
            button = ttk.Button(
                row, text=str(value), width=3, command=lambda v=value: self.on_digit(v)
            )
            button.pack(side="left", padx=1)
            self._buttons[str(value)] = button

    def _build_tool_row(self) -> None:
        row = ttk.Frame(self._frame, padding=(8, 6, 8, 0))
        row.pack()
        tools: tuple[tuple[str, str, Callable[[], None]], ...] = (
            ("clear", "清除", self.on_clear),
            ("undo", "Undo", self.on_undo),
            ("redo", "Redo", self.on_redo),
            ("hint", "提示", self.on_hint),
            ("check", "檢查", self.on_check),
            ("give_up", "自動解", self.on_give_up),
        )
        for name, text, command in tools:
            button = ttk.Button(row, text=text, width=6, command=command)
            button.pack(side="left", padx=2)
            self._buttons[name] = button

    def _build_status_bar(self) -> None:
        ttk.Label(self._frame, textvariable=self._status_var, padding=(8, 6, 8, 8)).pack(fill="x")

    def _bind_keys(self) -> None:
        # 綁在 toplevel：無論焦點在 Canvas 或按鈕上都收得到按鍵
        self._root.bind("<Key>", self.on_key)
        for sequence in _UNDO_SEQUENCES:
            self._root.bind(sequence, lambda _event: self.on_undo())
        for sequence in _REDO_SEQUENCES:
            self._root.bind(sequence, lambda _event: self.on_redo())

    # ---------- 開局 ----------

    def on_new_game(self) -> None:
        """「新遊戲」：進行中且有進度時先確認，避免誤按丟掉整局。"""
        if self._needs_new_game_confirmation() and not self._dialogs.ask_yes_no(
            "新遊戲", "放棄目前這局？"
        ):
            return
        self.start_game(self._selected_difficulty())

    def _needs_new_game_confirmation(self) -> bool:
        session = self._session
        return session is not None and not session.is_over and session.has_progress()

    def start_game(self, difficulty: Difficulty) -> None:
        """以指定難度出題並開新局；出題失敗時保留原本的局面。"""
        puzzle = self._generate_with_wait_cursor(difficulty)
        if puzzle is None:
            return
        self._stop_timer()
        self._session = GameSession(puzzle)
        self._selected = None
        self._wrong_cells = set()
        self._end_announced = False
        self._title_var.set(format_puzzle_title(puzzle))
        self._status_var.set("")
        self._redraw()
        self._update_buttons()
        # 計時從盤面畫出來之後才開始，出題等待時間不算進成績
        self._start_timer()
        self._canvas.focus_set()

    def _generate_with_wait_cursor(self, difficulty: Difficulty) -> Puzzle | None:
        """主執行緒同步出題（spec 決策 9），期間顯示等待游標。"""
        self._root.configure(cursor="watch")
        # 不先處理待辦的重繪，游標要等出題結束才會換，玩家看不到等待提示
        self._root.update_idletasks()
        try:
            puzzle: Puzzle | None = self._puzzle_factory(difficulty)
        except (ValueError, RuntimeError) as exc:
            self._dialogs.show_error("出題失敗", f"無法產生「{difficulty.label}」題目：{exc}")
            puzzle = None
        finally:
            self._root.configure(cursor="")
        return puzzle

    def _selected_difficulty(self) -> Difficulty:
        label = self._difficulty_var.get()
        for difficulty in Difficulty:
            if difficulty.label == label:
                return difficulty
        return DEFAULT_DIFFICULTY

    # ---------- 輸入事件 ----------

    def on_canvas_click(self, event: tk.Event) -> None:
        """點擊盤面選格；點到盤面外不改變選取。"""
        self._canvas.focus_set()
        cell = pixel_to_cell(event.x, event.y, CELL_SIZE, MARGIN)
        if cell is None:
            return
        self._selected = cell
        self._redraw()

    def on_key(self, event: tk.Event) -> None:
        """方向鍵移動、1–9 填數、0/Delete/BackSpace 清除；其他按鍵忽略。"""
        keysym = getattr(event, "keysym", "")
        if keysym in DIRECTIONS:
            self._move_selection(keysym)
            return
        if keysym in CLEAR_KEYSYMS:
            self.on_clear()
            return
        digit = _digit_from_event(event)
        if digit is not None:
            self.on_digit(digit)

    def _move_selection(self, direction: str) -> None:
        # 尚未選格時第一次按方向鍵先選左上角，不直接位移，玩家才看得到起點
        if self._selected is None:
            self._selected = (0, 0)
        else:
            self._selected = move_selection(self._selected, direction)
        self._redraw()

    # ---------- 盤面操作（全部透過 GameSession） ----------

    def on_digit(self, value: int) -> None:
        session = self._session
        if session is None:
            return
        if self._selected is None:
            self._status_var.set("請先選擇一個格子")
            return
        changed = session.set_cell(*self._selected, value)
        self._after_action(board_changed=changed)

    def on_clear(self) -> None:
        session = self._session
        if session is None or self._selected is None:
            return
        changed = session.clear_cell(*self._selected)
        self._after_action(board_changed=changed)

    def on_undo(self) -> None:
        session = self._session
        if session is None:
            return
        self._after_action(board_changed=session.undo() is not None)

    def on_redo(self) -> None:
        session = self._session
        if session is None:
            return
        self._after_action(board_changed=session.redo() is not None)

    def on_hint(self) -> None:
        """提示選取格（若適用），否則由 GameSession 隨機挑格；提示後選取該格方便玩家看到。"""
        session = self._session
        if session is None:
            return
        selected = self._selected
        target = session.hint(*selected) if selected is not None else session.hint()
        if target is not None:
            self._selected = target
            self._status_var.set(f"提示：第 {target[0] + 1} 列第 {target[1] + 1} 欄")
        self._after_action(board_changed=target is not None)

    def on_check(self) -> None:
        """對照正解標出錯格；不改盤面，紅底留到下次修改盤面時清除。"""
        session = self._session
        if session is None or session.is_over:
            return
        self._wrong_cells = session.check()
        count = len(self._wrong_cells)
        self._status_var.set(f"發現 {count} 個錯誤" if count else "目前填入的數字都正確")
        self._redraw()

    def on_give_up(self) -> None:
        """自動解：填入正解並結束本局（不計成績）。"""
        session = self._session
        if session is None or session.is_over:
            return
        session.give_up()
        self._after_action(board_changed=True)

    def _after_action(self, *, board_changed: bool) -> None:
        """每個改盤面操作後的統一收尾（spec §6）：重繪、更新按鈕、偵測本局結束。"""
        session = self._session
        if session is None:
            return
        if board_changed:
            self._wrong_cells.clear()
        self._redraw()
        self._update_buttons()
        if session.is_over and not self._end_announced:
            self._end_announced = True
            self._stop_timer()
            self._announce_end(session)

    def _announce_end(self, session: GameSession) -> None:
        elapsed = format_elapsed(self.elapsed_seconds())
        if session.state is GameState.SOLVED:
            self._status_var.set(f"完成！用時 {elapsed}")
            message = f"用時：{elapsed}\n使用提示：{session.hint_count} 次"
            self._dialogs.show_info("恭喜完成", message)
        else:
            # 自動解是玩家主動要求的，不再跳對話框打斷，只在狀態列說明
            self._status_var.set("已自動解，本局不計成績")

    def _update_buttons(self) -> None:
        session = self._session
        is_over = session is None or session.is_over
        for name in _PLAY_CONTROLS:
            self._set_enabled(name, not is_over)
        self._set_enabled("undo", session is not None and session.can_undo())
        self._set_enabled("redo", session is not None and session.can_redo())

    def _set_enabled(self, name: str, enabled: bool) -> None:
        self._buttons[name].state(["!disabled"] if enabled else ["disabled"])

    # ---------- 繪製 ----------

    def _redraw(self) -> None:
        """整盤重畫；81 格的 Canvas 物件量很小，全部重建比追蹤差異簡單可靠。"""
        self._canvas.delete("all")
        session = self._session
        if session is None:
            return
        # 衝突只算一次再傳給每格，避免 81 次重複掃描
        conflicts = session.board.conflicts()
        for row in range(SIZE):
            for col in range(SIZE):
                self._draw_cell(session, row, col, conflicts)
        self._draw_grid_lines()

    def _draw_cell(self, session: GameSession, row: int, col: int, conflicts: set[Cell]) -> None:
        style = cell_style(
            session,
            row,
            col,
            selected=self._selected,
            conflicts=conflicts,
            wrong_cells=self._wrong_cells,
        )
        x0, y0, x1, y1 = cell_to_pixel(row, col, CELL_SIZE, MARGIN)
        self._canvas.create_rectangle(x0, y0, x1, y1, fill=style.background, outline="")
        value = session.board.get(row, col)
        if value == EMPTY:
            return
        self._canvas.create_text(
            (x0 + x1) / 2,
            (y0 + y1) / 2,
            text=str(value),
            fill=style.text_color,
            font=self._digit_fonts[style.bold],
            tags=(_digit_tag(row, col),),
        )

    def _draw_grid_lines(self) -> None:
        # 先畫細線再畫粗線，交叉處才不會被灰色細線蓋過宮界
        end = MARGIN + SIZE * CELL_SIZE
        indices = sorted(range(SIZE + 1), key=lambda index: index % BOX_SIZE == 0)
        for index in indices:
            color, width = THICK_LINE if index % BOX_SIZE == 0 else THIN_LINE
            position = MARGIN + index * CELL_SIZE
            self._canvas.create_line(position, MARGIN, position, end, fill=color, width=width)
            self._canvas.create_line(MARGIN, position, end, position, fill=color, width=width)

    # ---------- 計時 ----------

    def _start_timer(self) -> None:
        self._start_time = time.monotonic()
        self._stopped_elapsed = None
        self._timer_var.set(format_elapsed(0))
        self._timer_job = self._root.after(TICK_MS, self._tick)

    def _tick(self) -> None:
        # 每次從 monotonic 重算經過時間，after() 的排程誤差不會累積到顯示上
        self._timer_job = None
        self._timer_var.set(format_elapsed(self.elapsed_seconds()))
        self._timer_job = self._root.after(TICK_MS, self._tick)

    def _stop_timer(self) -> None:
        if self._timer_job is not None:
            self._root.after_cancel(self._timer_job)
            self._timer_job = None
        if self._stopped_elapsed is None:
            self._stopped_elapsed = time.monotonic() - self._start_time
        self._timer_var.set(format_elapsed(self._stopped_elapsed))

    # ---------- 錯誤處理與關閉 ----------

    def _on_callback_error(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        """事件處理中的非預期例外：完整 traceback 印到 stderr，並以對話框告知玩家。"""
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)
        # 視窗已在關閉途中時對話框無法顯示，錯誤已印到 stderr，不再往外拋
        with contextlib.suppress(tk.TclError):
            self._dialogs.show_error(
                "發生錯誤", f"操作時發生非預期錯誤：\n{exc_type.__name__}: {exc_value}"
            )

    def destroy(self) -> None:
        """拆掉本畫面但保留 toplevel：取消計時、解除按鍵綁定、銷毀容器。

        先取消 after 排程，否則容器銷毀後計時回呼仍會觸發並操作已不存在的元件。
        """
        if self._timer_job is not None:
            self._root.after_cancel(self._timer_job)
            self._timer_job = None
        for sequence in ("<Key>", *_UNDO_SEQUENCES, *_REDO_SEQUENCES):
            self._root.unbind(sequence)
        self._frame.destroy()

    def close(self) -> None:
        """關閉整個視窗（WM_DELETE_WINDOW）：先拆本畫面，再銷毀 toplevel。"""
        self.destroy()
        self._root.destroy()


def run() -> int:
    """建立主視窗並進入事件迴圈，啟動直接開一局「中等」（spec §5）。

    無圖形顯示環境時 tk.Tk() 會拋 tk.TclError，交由呼叫端（__main__）處理。
    """
    root = tk.Tk()
    SudokuApp(root)
    root.mainloop()
    return 0
