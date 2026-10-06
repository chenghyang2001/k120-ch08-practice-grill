# 數獨 Python App 規格書（v1）

> 狀態：**待確認**　｜　來源：2026-10-06 grill-me-dev 訪談 13 項決策

## 1. 目標

一個用 `uv` 管理的 Python 桌面數獨 app：能**自動出題（保證唯一解）**、讓玩家在 `tkinter` 視窗中**遊玩**，並提供**提示、自動解、計時、Undo/Redo**。

非目標（延到 v2）：鉛筆註記、存檔/讀檔、暫停計時、依解題技巧評難度、每日一題。

## 2. 決策總表

| # | 面向 | 決策 |
| --- | --- | --- |
| 1 | 範圍 | 玩＋解，分階段：解題器 → 出題器 → 遊玩介面 |
| 2 | 介面 | `tkinter` 桌面 GUI；核心模組**不得 import tkinter** |
| 3 | 解題演算法 | 回溯＋候選數＋MRV；提供 `count_solutions(board, limit=2)` |
| 4 | 難度 | 依提示數 3 級：簡單 36–40／中等 30–35／困難 25–29；`rate_difficulty()` 獨立函式 |
| 5 | 錯誤提示 | 即時標紅規則衝突；「檢查」按鈕對照正解；Puzzle 同時存正解；給定格鎖定 |
| 6 | v1 功能 | 提示、自動解、計時器、Undo/Redo；用自動解即結束本局；提示記次數 |
| 7 | 結構 | `src/sudoku/`：board / solver / generator / game / gui；GUI 只呼叫 game |
| 8 | 隨機性 | `generate(difficulty, seed=None)`，用 `random.Random(seed)`；seed 存入 Puzzle 並於 GUI 顯示為題號 |
| 9 | 效能 | 主執行緒同步出題＋等待游標；預算：困難每題 < 1 秒；重試上限 20 次，失敗接受最接近結果 |
| 10 | 操作 | Canvas 畫盤面＋1–9 數字按鈕；滑鼠/方向鍵選格、鍵盤填數 |
| 11 | 生命週期 | 狀態機 PLAYING → SOLVED／GAVE_UP（見 §5） |
| 12 | Undo × 提示 | 提示時從 Undo 堆疊濾除該格紀錄、Redo 全清 |
| 13 | 流程 | 規格先行 → 四批實作，每批 code-writer → code-qa → code-reviewer |

環境：`requires-python = ">=3.12"`（開發機為 3.14.7、uv 0.12.23）。

## 3. 專案結構

```
k120-ch08-practice-grill/
├── pyproject.toml          # entry point: sudoku = "sudoku.__main__:main"
├── src/sudoku/
│   ├── __init__.py
│   ├── __main__.py         # 啟動 GUI
│   ├── board.py
│   ├── solver.py
│   ├── generator.py
│   ├── game.py
│   └── gui/
│       ├── __init__.py
│       └── app.py
└── tests/
    ├── test_board.py
    ├── test_solver.py
    ├── test_generator.py
    └── test_game.py
```

相依方向（不可反向）：

```
gui/app.py ──▶ game.py ──▶ board.py
                  │            ▲
                  └──▶ generator.py ──▶ solver.py
```

## 4. 模組介面

座標一律 `(row, col)`，0-based，範圍 0–8；數值 1–9，`0` 表示空格。

### 4.1 `board.py`

```python
Grid = tuple[tuple[int, ...], ...]   # 9×9 不可變，用於 Puzzle

class Board:
    @classmethod
    def from_grid(cls, grid: Grid | list[list[int]]) -> "Board": ...
    @classmethod
    def from_string(cls, s: str) -> "Board": ...   # 81 字元，'0' 或 '.' 為空格
    def get(self, row: int, col: int) -> int: ...
    def set(self, row: int, col: int, value: int) -> None: ...  # 不檢查鎖定（由 game 負責）
    def is_given(self, row: int, col: int) -> bool: ...
    def lock(self, row: int, col: int) -> None: ...             # 提示用：將格子設為給定
    def candidates(self, row: int, col: int) -> set[int]: ...   # 依同行/列/宮計算
    def conflicts(self) -> set[tuple[int, int]]: ...            # 所有違反規則的格子
    def is_full(self) -> bool: ...
    def to_grid(self) -> Grid: ...
    def copy(self) -> "Board": ...
```

- 數值不在 0–9、座標越界 → `ValueError`
- 型別錯誤（非 int、bool）→ `TypeError`

### 4.2 `solver.py`

```python
def solve(board: Board) -> Board | None: ...                 # 回傳新 Board，不修改輸入；無解回傳 None
def count_solutions(board: Board, limit: int = 2) -> int: ...  # 數到 limit 即停
```

- 演算法：每次選候選數最少的空格（MRV），依序嘗試候選，回溯
- 輸入盤面本身已有衝突 → 直接回傳 `None` / `0`

### 4.3 `generator.py`

```python
class Difficulty(Enum):
    EASY = "簡單"     # 提示數 36–40
    MEDIUM = "中等"   # 30–35
    HARD = "困難"     # 25–29

@dataclass(frozen=True)
class Puzzle:
    givens: Grid
    solution: Grid
    difficulty: Difficulty   # 玩家所選難度
    clue_count: int          # 實際提示數（可能因退而求其次而超出區間）
    seed: int

def generate(difficulty: Difficulty, seed: int | None = None) -> Puzzle: ...
def rate_difficulty(givens: Grid) -> Difficulty: ...   # v1：依提示數
```

出題流程：

1. `rng = random.Random(seed)`；以隨機順序候選填滿空盤，產生完整解
2. 隨機順序逐格挖洞；每挖一格用 `count_solutions(limit=2)` 驗證，非唯一解則填回
3. 提示數降到目標區間上限內即停（目標值在區間內隨機取）
4. 未達區間 → 換新完整盤面重試，最多 20 次；仍失敗則取提示數最少的那次結果

實作約束（第 1 批 code review 後補充）：

- **隨機填盤**：`solver.py` 內部搜尋接受可選的 `rng`（打亂候選嘗試順序），並提供模組內部函式 `_random_fill(rng: random.Random) -> Grid` 給 generator 用；公開的 `solve` / `count_solutions` 簽名與決定性行為不變。generator 不得自己另寫一套回溯
- **seed 值域**：合法範圍 `0 <= seed < SEED_SPACE`（`SEED_SPACE = 2**32`），超出拋 `ValueError`；`seed=None` 時改用 `random.SystemRandom().randrange(SEED_SPACE)` 挑題號，不受全域 random 狀態影響。docstring 須註明：同一 seed 只保證在同一 Python 大版本、同一版 generator 演算法下重現同一題
- **顯示名稱**：`Difficulty` 提供 `label` property 作為顯示用中文名稱，GUI 一律透過 `label` 取名稱，不直接讀 `value`
- **給定格旗標**：`Board.set(r, c, 0)` 不會清除給定旗標。因此 `Puzzle.givens` 一律以 `to_grid()` 輸出的 `Grid` 存放，game 端以 `Board.from_grid(puzzle.givens)` 重建，不可直接傳遞挖洞過程中的 Board 物件

### 4.4 `game.py`

```python
class GameState(Enum):
    PLAYING = auto()
    SOLVED = auto()
    GAVE_UP = auto()

@dataclass(frozen=True)
class Move:
    row: int
    col: int
    old: int
    new: int

class GameSession:
    def __init__(self, puzzle: Puzzle): ...
    state: GameState
    board: Board
    hint_count: int
    def set_cell(self, row: int, col: int, value: int) -> bool: ...  # 唯一修改入口；給定格/非 PLAYING 回傳 False
    def clear_cell(self, row: int, col: int) -> bool: ...            # 等同 set_cell(..., 0)
    def undo(self) -> Move | None: ...
    def redo(self) -> Move | None: ...
    def can_undo(self) -> bool: ...
    def can_redo(self) -> bool: ...
    def hint(self, row: int | None = None, col: int | None = None) -> tuple[int, int] | None: ...
    def check(self) -> set[tuple[int, int]]: ...   # 與正解不符的已填格
    def give_up(self) -> None: ...                 # 填入正解，state → GAVE_UP
    def has_progress(self) -> bool: ...            # 是否填過任何格（新遊戲確認用）
```

## 5. 遊戲規則與狀態機

```
           新遊戲(選難度)
                │
                ▼
  ┌────────▶ PLAYING ──填滿且全對──▶ SOLVED（停表，顯示時間＋提示次數）
  │             │
  │             └──按「自動解」──▶ GAVE_UP（停表，填入答案，不計成績）
  │
  └── 任何狀態按「新遊戲」；若 PLAYING 且 has_progress() → 先確認「放棄目前這局？」
```

- 啟動 app 直接開一局「中等」
- 難度下拉選單改變不會立即重開，按「新遊戲」才生效
- SOLVED／GAVE_UP 後盤面鎖定、Undo/Redo 失效
- 計時從盤面顯示開始，最小化不暫停
- 填滿但有錯：不提示，維持 PLAYING
- 新填數（值改變）→ 推入 Undo、清空 Redo；填入相同值視為無操作

**提示**：

- 有選格且該格非給定、且值 ≠ 正解 → 填該格；否則從「空格或錯格」中隨機挑一格
- 填入正解並 `lock()`，`hint_count += 1`
- 從 Undo 堆疊濾除所有涉及該格的 Move，Redo 全清；提示本身**不可 Undo**
- 提示後若填滿且全對 → SOLVED

## 6. GUI 規格（`gui/app.py`）

- **版面**：上方列（難度下拉、新遊戲、題號 #seed、計時）／中央 Canvas 盤面／下方 1–9 數字按鈕＋清除、Undo、Redo、提示、檢查、自動解
- **選格**：滑鼠點擊、方向鍵移動；選取格高亮，同行/列/宮淡色，同數字淡色高亮
- **填數**：鍵盤 `1`–`9` 或數字按鈕；`0`/`Delete`/`Backspace` 清除；`Ctrl+Z`/`Ctrl+Y`
- **顏色**：給定格黑色粗體、玩家填入藍色、衝突數字紅色、「檢查」後錯格紅底（下次修改時清除）
- **格線**：宮界粗線、格界細線
- 點擊座標→行列換算為純函式 `pixel_to_cell(x, y, cell_size, margin) -> tuple[int, int] | None`，可單元測試
- 出題時游標 `watch`；完成時跳訊息框顯示用時與提示次數

## 7. 邊界條件

| 情境 | 預期 |
| --- | --- |
| 輸入盤面已有衝突 | `solve` → `None`、`count_solutions` → 0 |
| 空盤 | `count_solutions(limit=2)` → 2 |
| 修改給定格 | `set_cell` 回傳 False，盤面不變 |
| 非 PLAYING 狀態操作 | 所有修改/Undo/提示回傳 False/None |
| 無空格無錯格時按提示 | 回傳 None（實務上此時已 SOLVED） |
| 困難挖不到 29 格以下 | 重試 20 次後接受最接近結果，不拋例外 |
| 數值越界（10、-1） | `ValueError` |
| 點擊盤面外 | `pixel_to_cell` → None |

## 8. 測試清單（QA 20+ case）

**test_board.py**

1. `from_string` / `to_grid` 往返一致
2. `candidates` 正確排除同行/列/宮
3. `conflicts` 偵測行、列、宮重複
4. 越界值與座標 → `ValueError`

**test_solver.py**
5. 解出一般題，解答合法且保留給定數
6. 解出「世界最難數獨」（Arto Inkala 2012）
7. 無解盤面 → `None`
8. 多解盤面 `count_solutions` → 2；空盤 → 2
9. `solve` 不修改輸入盤面

**test_generator.py**
10. 相同 seed 產生相同 Puzzle
11. 三種難度各數個 seed：唯一解
12. 提示數落在區間（或為退而求其次結果且 ≤ 區間上限＋容差）
13. `solution` 與 `solve(givens)` 一致
14. 效能：困難 × 20 seed，每題 < 1 秒
15. `rate_difficulty` 邊界值（25/29/30/35/36/40）

**test_game.py**
16. 給定格不可改
17. Undo/Redo 基本流程；新操作清空 Redo
18. 填滿全對 → SOLVED，之後操作無效
19. `give_up` → GAVE_UP、盤面等於正解
20. 提示 × Undo 衝突情境（§ 決策 12 的 4 步）
21. 提示計次、提示格被鎖定
22. `check` 回傳錯格；`has_progress`

**GUI**
23. `pixel_to_cell` 邊界（格線上、盤面外）
24. `uv run sudoku` 啟動後截圖驗證畫面

## 9. 實作批次

| 批次 | 內容 | 驗收 |
| --- | --- | --- |
| 1 | `pyproject.toml`、`board.py`、`solver.py` ＋測試 | 測試 1–9 通過 |
| 2 | `generator.py` ＋測試 | 測試 10–15 通過 |
| 3 | `game.py` ＋測試 | 測試 16–22 通過 |
| 4 | `gui/app.py`、`__main__.py` | 測試 23、截圖驗證 |

每批：code-writer → code-qa（複雜度：complex）→ code-reviewer；通過後 commit + push。

Git 前置：分支 `master` 改名 `main`、建 `.gitignore`、`gh repo create chenghyang2001/k120-ch08-practice-grill --public`。
