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

### Homebrew

依存関係のインストールに使用します。未導入の場合は先にインストールしてください。

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### Hugging Face アカウントとアクセストークン

話者分離モデル (`pyannote/speaker-diarization-community-1`) の利用に必要です。

1. [https://huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) でアクセストークン (`hf_xxx...`) を発行する
2. 以下のモデルページでアクセス申請（利用規約への同意）を行う
   - [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
   - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)

---

## インストール

### A. Homebrew Cask（配布版・推奨）

ビルド済みアプリを Homebrew 経由でインストールします。

```bash
brew install --cask nanasi-apps/tap/transcriber
```

インストール後、アプリを起動する前に **HF_TOKEN を macOS のシステム環境変数** として設定する必要があります。  
macOS の GUI アプリはターミナルのシェル環境を引き継がないため、`~/.zshrc` への追記では反映されません。

#### HF_TOKEN の設定方法

**① 今すぐ反映（現在のログインセッションのみ）**

```bash
launchctl setenv HF_TOKEN "hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

設定後、Transcriber を起動（または再起動）してください。

**② 再起動後も永続化する**

`~/Library/LaunchAgents/me.transcriber.env.plist` を以下の内容で作成します。

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>me.transcriber.env</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/launchctl</string>
    <string>setenv</string>
    <string>HF_TOKEN</string>
    <string>hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
```

作成後、ログインエージェントとして読み込みます。

```bash
launchctl load ~/Library/LaunchAgents/me.transcriber.env.plist
```

次回ログイン以降は自動で環境変数が設定されます。

---

### B. ソースからビルド（開発者向け）

`Brewfile` から次の依存関係をまとめて導入します。

- `python@3.13`
- `uv`
- `node`
- `pnpm`
- `ffmpeg`

#### 1. リポジトリのクローン

```bash
git clone https://github.com/nanasi-apps/transcriber
cd transcriber
```

#### 2. セットアップスクリプトの実行

```bash
./setup.sh
```

スクリプトが以下を自動で行います。

1. `brew bundle` で `Brewfile` の依存関係をインストール
2. `.env.local` が未作成の場合、`HF_TOKEN` の入力プロンプトを表示（またはスキップして雛形を作成）
3. バックエンドの依存関係インストール (`uv sync --project backend --python python3.13`)
4. フロントエンドの依存関係インストール (`pnpm install --frozen-lockfile`)

Homebrew だけ先に反映したい場合は単独でも実行できます。

```bash
brew bundle install
```

`.env.local` を手動で作成する場合:

```
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

雛形は `.env.local.example` にあります。

#### 3. 起動

```bash
./start.sh
```

バックエンド (FastAPI) と Electron が同時に起動します。

| プロセス | 説明 |
|---|---|
| `BACKEND` | FastAPI サーバー (`http://127.0.0.1:8765`) |
| `ELECTRON` | Electron アプリ |

---

## ビルド（配布用）

```bash
pnpm --dir frontend build:mac
```

| 出力先 | 内容 |
|---|---|
| `frontend/out/` | ビルド成果物 |
| `frontend/dist/` | 配布用 `.dmg` |

---

## リリースと自動更新

GitHub に `v*` タグを push すると、以下が自動で行われます。

1. GitHub Releases に arm64 の `.dmg` を公開
2. `nanasi-apps/homebrew-tap` の Cask を自動更新

> この自動更新には、Actions secret `TAP_GITHUB_TOKEN` が必要です。

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
├── Brewfile              # Homebrew 依存関係
├── setup.sh              # セットアップスクリプト
├── start.sh              # 起動スクリプト
└── .env.local            # ローカル環境変数 (Git 管理外)
```
