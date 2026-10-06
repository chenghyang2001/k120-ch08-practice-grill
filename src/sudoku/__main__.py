"""數獨 app 進入點（`uv run sudoku` 或 `python -m sudoku`）：啟動 tkinter 視窗。

tkinter 在延遲匯入：部分 Linux 發行版或精簡版 Python 未附 Tcl/Tk，
直接在模組頂層 import 會讓使用者只看到一長串 traceback，這裡改成明確的錯誤訊息。
"""

import sys


def _print_error(message: str, fallback: str) -> None:
    """輸出錯誤到 stderr；主控台編碼（如 cp950）無法顯示時改用 ASCII 訊息，避免二次崩潰。"""
    try:
        print(message, file=sys.stderr)
    except UnicodeEncodeError:
        print(fallback, file=sys.stderr)


def main() -> int:
    """啟動 GUI；tkinter 不可用或無法建立視窗時印出原因並回傳 1。"""
    try:
        import tkinter

        from sudoku.gui.app import run
    except ImportError as exc:
        _print_error(
            f"錯誤：無法載入 tkinter，請確認 Python 安裝時有包含 Tcl/Tk（{exc}）",
            f"Error: tkinter is not available ({exc})",
        )
        return 1
    try:
        return run()
    except tkinter.TclError as exc:
        _print_error(
            f"錯誤：無法建立視窗，可能沒有圖形顯示環境（{exc}）",
            f"Error: cannot open a window, no display available? ({exc})",
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
