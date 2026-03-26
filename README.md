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

以下のツールを事前にインストールしてください。

- **uv** — Python パッケージマネージャー  
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **pnpm** — Node パッケージマネージャー  
  ```bash
  npm install -g pnpm
  ```
- **Hugging Face アカウント** — 話者分離モデル (`pyannote/speaker-diarization-3.1`) の利用に必要  
  [https://huggingface.co/pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) でモデルへのアクセス申請を行い、アクセストークンを取得してください。

---

## セットアップ

### 1. リポジトリのクローン

```bash
git clone <repository-url>
cd transcriber
```

### 2. 環境変数の設定

プロジェクトルートに `.env.local` を作成し、Hugging Face のアクセストークンを設定します。

```bash
cp .env.local.example .env.local  # example がない場合は直接作成
```

`.env.local` の内容:

```
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 3. バックエンドのセットアップ

```bash
cd backend
uv sync
```

### 4. フロントエンドのセットアップ

```bash
cd frontend
pnpm install
```

---

## 開発サーバーの起動

`frontend` ディレクトリで以下を実行すると、バックエンド (FastAPI) と Electron が同時に起動します。

```bash
cd frontend
pnpm dev
```

| プロセス | 説明 |
|---|---|
| `BACKEND` | FastAPI サーバー (`http://127.0.0.1:8765`) |
| `ELECTRON` | Electron アプリ |

---

## ビルド (配布用)

```bash
cd frontend
pnpm build:mac
```

ビルド成果物は `frontend/out/` に生成されます。

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
