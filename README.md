# Transcriber

MP4 などの動画・音声ファイルから、話者分離付きの文字起こしを行うデスクトップアプリです。  
**Electron + Vue 3** のフロントエンドと、**Python (FastAPI)** のバックエンドで構成されています。

> **動作環境**: macOS (Apple Silicon) 専用です。

---

## 技術スタック

| レイヤー | 技術 |
|---|---|
| フロントエンド | Electron 35, Vue 3, TypeScript |
| バックエンド | Python 3.13, FastAPI, uvicorn |
| 文字起こし | Whisper MLX (`mlx-whisper`) |
| 話者分離 | pyannote.audio |
| パッケージ管理 (Python) | uv |
| パッケージ管理 (Node) | pnpm |

---

## 前提条件

以下を事前に用意してください。

- **Homebrew** — 依存関係のインストールに使用します  
  ```bash
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  ```
- **Hugging Face アカウント** — 話者分離モデル (`pyannote/speaker-diarization-3.1`) の利用に必要  
  [https://huggingface.co/pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) でモデルへのアクセス申請を行い、アクセストークンを取得してください。

`Brewfile` から次の依存関係をまとめて導入します。

- `python@3.13`
- `uv`
- `node`
- `pnpm`
- `ffmpeg`

---

## セットアップ

### 1. リポジトリのクローン

```bash
git clone https://github.com/nanasi-apps/transcriber
cd transcriber
```

### 2. セットアップスクリプトの実行

```bash
./setup.sh
```

スクリプトが以下を自動で行います:

1. `brew bundle` で `Brewfile` の依存関係をインストール
2. `.env.local` が未作成の場合、`HF_TOKEN` の入力または雛形ファイルの作成
3. バックエンドの依存関係インストール (`uv sync --project backend --python python3.13`)
4. フロントエンドの依存関係インストール (`pnpm install --frozen-lockfile`)

Homebrew だけ先に反映したい場合は、単独で次も実行できます。

```bash
brew bundle install
```

既存の Homebrew パッケージは無闇に更新せず、足りない依存関係だけを追加します。

`.env.local` を手動で作成する場合:

```
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

雛形は `.env.local.example` にあります。

---

## 起動

```bash
./start.sh
```

バックエンド (FastAPI) と Electron が同時に起動します。

| プロセス | 説明 |
|---|---|
| `BACKEND` | FastAPI サーバー (`http://127.0.0.1:8765`) |
| `ELECTRON` | Electron アプリ |

---

## ビルド (配布用)

```bash
pnpm --dir frontend build:mac
```

ビルド成果物は `frontend/out/` に生成されます。
ビルド済みの `.dmg` は `frontend/dist/` に生成されます。

---

## Homebrew Cask

GitHub に `v*` タグを push すると、GitHub Releases に arm64 の `.dmg` を公開し、
`nanasi-apps/homebrew-tap` の cask も自動更新されます。

```bash
brew install --cask nanasi-apps/tap/transcriber
```

この自動更新には、Actions secret `TAP_GITHUB_TOKEN` が必要です。

---

## プロジェクト構成

```
transcriber/
├── backend/              # Python バックエンド
│   ├── src/transcriber/  # アプリケーションコード
│   │   ├── server.py     # FastAPI サーバー
│   │   ├── pipeline.py   # 文字起こしパイプライン
│   │   ├── asr.py        # Whisper MLX による音声認識
│   │   └── diarization.py# pyannote による話者分離
│   └── pyproject.toml
├── frontend/             # Electron + Vue 3 フロントエンド
│   ├── src/
│   └── package.json
└── .env.local            # ローカル環境変数 (Git 管理外)
```
