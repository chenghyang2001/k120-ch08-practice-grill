"""數獨 app 進入點（`uv run sudoku` 或 `python -m sudoku`）。

第 1 批暫時版本：GUI 於第 4 批實作，屆時改寫為啟動 tkinter 視窗。
"""

import sys


def main() -> int:
    """印出尚未實作訊息並回傳結束碼 0。"""
    try:
        print("GUI 尚未實作（第 4 批）")
    except UnicodeEncodeError as exc:
        # Windows cp950 主控台可能無法輸出部分字元，改用 ASCII 訊息避免崩潰
        print(f"GUI not implemented yet (batch 4): {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
