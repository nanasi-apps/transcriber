#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── 色付き出力 ────────────────────────────────────────────────
info()    { echo -e "\033[1;34m[INFO]\033[0m  $*"; }
success() { echo -e "\033[1;32m[OK]\033[0m    $*"; }
warn()    { echo -e "\033[1;33m[WARN]\033[0m  $*"; }
error()   { echo -e "\033[1;31m[ERROR]\033[0m $*" >&2; exit 1; }

# ── 前提条件チェック ──────────────────────────────────────────
info "前提条件を確認しています..."

command -v uv   >/dev/null 2>&1 || error "uv が見つかりません。https://astral.sh/uv からインストールしてください。"
command -v pnpm >/dev/null 2>&1 || error "pnpm が見つかりません。'npm install -g pnpm' でインストールしてください。"

success "uv:   $(uv --version)"
success "pnpm: $(pnpm --version)"

# ── .env.local の確認 ─────────────────────────────────────────
ENV_FILE="$ROOT/.env.local"

if [ ! -f "$ENV_FILE" ]; then
  warn ".env.local が見つかりません。作成します。"
  echo ""
  echo "Hugging Face のアクセストークンが必要です。"
  echo "  取得先: https://huggingface.co/settings/tokens"
  echo "  モデルへのアクセス申請: https://huggingface.co/pyannote/speaker-diarization-3.1"
  echo ""
  read -rp "HF_TOKEN を入力してください: " hf_token
  if [ -z "$hf_token" ]; then
    warn "HF_TOKEN が空です。後で .env.local に手動で設定してください。"
    echo "HF_TOKEN=" > "$ENV_FILE"
  else
    echo "HF_TOKEN=$hf_token" > "$ENV_FILE"
    success ".env.local を作成しました。"
  fi
else
  success ".env.local が存在します。"
fi

# ── バックエンドのセットアップ ────────────────────────────────
info "バックエンドの依存関係をインストールしています..."
cd "$ROOT/backend"
uv sync
success "バックエンドのセットアップ完了。"

# ── フロントエンドのセットアップ ──────────────────────────────
info "フロントエンドの依存関係をインストールしています..."
cd "$ROOT/frontend"
pnpm install
success "フロントエンドのセットアップ完了。"

# ── 完了 ──────────────────────────────────────────────────────
echo ""
echo -e "\033[1;32m========================================\033[0m"
echo -e "\033[1;32m  セットアップが完了しました！\033[0m"
echo -e "\033[1;32m========================================\033[0m"
echo ""
echo "起動するには次のコマンドを実行してください:"
echo "  ./start.sh"
