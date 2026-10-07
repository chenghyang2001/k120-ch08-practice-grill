# Session 1 摘要：數獨 Python App（grill-me-dev 訪談 → 四批實作 v1）

- 日期：2026-10-06 ～ 2026-10-07
- 機器：DESKTOP-6LST1BR
- Repo：<https://github.com/chenghyang2001/k120-ch08-practice-grill（分支> `main`）

## 完成事項

### 需求訪談（grill-me-dev）

- 用 `/grill-me-dev` 逐題訪談 13 個開發決策（範圍、介面、解題演算法、難度、錯誤提示、v1 功能、模組結構、隨機性、效能、操作、狀態機、Undo×提示衝突、交付流程），使用者全數採用建議答案
- 實作期間再追問 2 題（決策 14 題號綁定難度、決策 15 提示格綠色粗體），加上 code review 後補記的決策 16（v1 GUI 細節），共 16 項
- 產出規格書 `doc/spec.md`（決策表、模組介面、狀態機、GUI 規格、邊界條件、24 項測試清單、4 批實作計畫）

### 四批實作（每批 code-writer → code-qa → code-reviewer）

- 第 1 批 `57b629f`：`board.py`（盤面、給定格、候選數、衝突）＋ `solver.py`（回溯＋候選數＋MRV、`count_solutions(limit)`），QA 兩輪 FAIL（測試題字串抄錯）後通過，70 測試
- 第 2 批 `07741af`：`generator.py`（3 級難度、seed 注入、重試 20 次退而求其次）＋ solver 的 `_random_fill(rng)`，206 測試；reviewer 實測 900 題全唯一解、困難最慢 0.143 秒
- 第 3 批 `7fae855`：`game.py`（PLAYING/SOLVED/GAVE_UP 狀態機、`set_cell` 單一入口、Undo/Redo、提示鎖定並濾除 Undo 紀錄），271 測試；QA 7200 步隨機玩局不變式全過
- 第 4 批 `652dfee`：`gui/layout.py`（純函式）＋ `gui/app.py`（tkinter Canvas）＋ `__main__.py`，決策 14、15 實作，390 測試（3.12/Tk 8.6 與 3.14/Tk 9.0 皆 0 skip），實機截圖驗證
- 規格同步 `97ee593`：§3 結構、相依圖、決策 16、狀態改為「v1 已實作」

### 專案設定

- 分支 `master` 改名 `main`；`gh repo create` 公開 repo
- `.gitignore`（Python、機密、當機檔、`.claude/session-state.md`）、`.gitattributes`（`* text=auto eol=lf`）
- `pyproject.toml`：hatchling src layout、`sudoku` 進入點、dev 依賴 pytest + ruff、`slow` marker、ruff line-length 100

## 關鍵技術筆記

- **給定格旗標陷阱**：`Board.set(r,c,0)` 不清除 is_given；Puzzle.givens 一律存 `to_grid()` 的 Grid，game 以 `Board.from_grid()` 重建
- **出題亂數**：`random.Random(f"{difficulty.name}:{seed}")`，同 seed 不同難度＝不同題；`seed=None` 用 `SystemRandom`；seed 值域 `0 <= seed < 2**32`
- **提示亂數**：`random.Random(f"hint:{seed}")`，與出題去相關
- **Undo×提示**：每筆 Move 只記單格；提示時從 Undo 濾除該格紀錄、Redo 全清，提示不可 Undo
- **字型**：Microsoft JhengHei 的數字粗細兩種字重幾乎無差別 → 盤面數字改 Segoe UI，中文介面仍用 JhengHei
- **Tk 8.6（uv 的 CPython 3.12）同一行程反覆 `Tk()` 會找不到 tk.tcl** → smoke 測試改 module scope 共用單一 root，`SudokuApp` 接受 master 並提供 `destroy()`
- **Windows 換行**：repo `core.autocrlf=true` 會讓 SHA256 比對失準 → 加 `.gitattributes` 強制 LF
- **NUL 字元事故**：writer 把 `b"\x00"` 寫成實際 NUL 位元組，pytest 無法收集、ruff 抓不到；原地 `write_bytes` 兩次未生效，改「寫新檔再 mv 覆蓋」才成功
- 主 Claude 兩次給錯 Arto Inkala 最難數獨字串；正確為 `800000000003600000070090200050007000000045700000100030001000068008500010090000400`

## 產出檔案

| 檔案 | 說明 |
| --- | --- |
| `doc/spec.md` | 規格書（16 項決策、介面、狀態機、GUI、測試清單） |
| `pyproject.toml`、`uv.lock` | uv 專案設定 |
| `src/sudoku/board.py` | 盤面模型 |
| `src/sudoku/solver.py` | MRV 回溯解題器、`_random_fill` |
| `src/sudoku/generator.py` | 出題器、Difficulty、Puzzle |
| `src/sudoku/game.py` | GameSession 狀態機、BoardView、is_hinted |
| `src/sudoku/gui/layout.py` | GUI 純函式（座標、樣式、格式） |
| `src/sudoku/gui/app.py` | tkinter 介面 |
| `src/sudoku/__main__.py` | `uv run sudoku` 進入點 |
| `tests/test_board.py`、`test_solver.py`、`test_generator.py`、`test_game.py`、`test_layout.py`、`test_app_smoke.py` | 共 390 測試 |
| `.gitignore`、`.gitattributes` | 版控設定 |

## HANDOFF（下次 session 優先處理）

### 立即行動

- [ ] 查出 `07741af`（第 2 批）是哪個程序自動 commit + push 的（共同作者標 Claude Haiku 4.5，12:44 在 reviewer 審查中提交，非本 session）；確認是否還會在其他 repo 繞過審查
- [ ] 使用者已表示 v1 即可、不需繼續；若日後重啟，先把下方 v1.1 候選清單寫進 `doc/spec.md`

### 進行中（需接續）

- 無。v1 已完成並推上 GitHub，工作區乾淨。使用者明確表示「it is ok now. no need to go further.」，v1.1 未啟動

### 注意事項

- v1.1 候選（reviewer 非必改建議，未寫入規格）：自動解前加確認框；本局結束後 `on_digit` 直接 return（避免蓋掉狀態列訊息）；盤面改變時清除過期的狀態列訊息；小鍵盤 NumLock 關閉時的 KP_* 鍵；Combobox 焦點時方向鍵雙重觸發；啟動出題失敗的半成品畫面；依平台挑字型
- v2 規劃（規格非目標）：鉛筆註記、存讀檔、暫停計時、依解題技巧評難度、每日一題、輸入題號重玩、高 DPI
- `generate()` 43 行超過 30 行上限（既有，未拆）
- QA 驗證時切 Python 版本會讓 uv 重建 `.venv`；還原用 `uv sync --python 3.12`（單用 `uv sync` 不會回到 3.12）
