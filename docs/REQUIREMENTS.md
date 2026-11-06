# 必要な環境（Focus & Cafe v2）

`scripts\setup_env.bat` をダブルクリックすると、以下を順番に自動で入れます（winget 使用・UAC の「はい」が必要）。
手動で揃える場合の一覧です。

## OS
- Windows 10（1809 以降）または Windows 11
  - `winget`（アプリ インストーラー）が必要。無ければ Microsoft Store から「アプリ インストーラー」を更新
  - ゲーム／サイト制限（`site_blocker.py` の hosts 書き換え）は管理者権限が必要な場合があります

## ランタイム
| ソフト | バージョン | 用途 | 入れ方 |
|---|---|---|---|
| Python | 3.12 系（3.10 以上で可） | バックエンド（venv）、常駐ワーカー、小窓 | `winget install Python.Python.3.12` |
| Node.js | LTS（20 以上） | フロントエンド（Vite 開発サーバー） | `winget install OpenJS.NodeJS.LTS` |
| Google Chrome | 最新 | 画面を開くブラウザ（他のブラウザでも可） | `winget install Google.Chrome` |
| curl | Windows 標準 | start_all.bat の起動確認 | 不要（Windows 10 1803 以降に同梱） |

## Python パッケージ
### backend/venv（`backend/requirements.txt`）
- fastapi[standard]（uvicorn を含む）
- sqlalchemy
- psutil
- pytest
- jpholiday

### システム側の Python（venv ではなく `pythonw` で起動するため）
- PySide6（小窓 `quick_widget.py`）
- psutil（常駐ワーカー。venv の pythonw で動かす場合は不要）

## Node パッケージ（`frontend/package.json`、`npm install` で入る）
- react 19 / react-dom 19
- vite 6 / @vitejs/plugin-react

## 任意（使う機能によって必要）
| 機能 | 必要なもの | 設定場所 |
|---|---|---|
| Google カレンダー連携・iPhone ショートカット | Google アカウント、Apps Script（`gas/gas_bridge.gs`）、Google ドライブ for desktop（G: ドライブ） | docs/SETUP_GOOGLE_SYNC.md |
| AI 日次プラン・支出 AI 判定 | Gemini API キー（Google AI Studio で無料発行） | マネー › 🤖 AI判定の設定 |
| Gmail からの支出取り込み | Gmail アプリパスワード | マネー › 入力 › メール取り込み |

## 使うポート
- 8000：バックエンド（FastAPI）… `127.0.0.1` のみ。使用中なら 8001〜8099 の空き
- 5173：フロントエンド（Vite）… `localhost` のみ。使用中なら 5174〜5199 の空き
- 実際の番号は起動時に `backend/data/runtime.json` に書かれる（`appctl.py`）

## 起動
```
scripts\setup_env.bat   （初回だけ。環境を自動で入れる）
start_all.bat   （毎回。バックエンド・フロント・ワーカー・小窓をまとめて起動）
stop_all.bat    （制限だけ止める。 stop_all.bat all で全部止める）
```
