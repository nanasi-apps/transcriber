#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── 色付き出力 ────────────────────────────────────────────────
info()  { echo -e "\033[1;34m[INFO]\033[0m  $*"; }
error() { echo -e "\033[1;31m[ERROR]\033[0m $*" >&2; exit 1; }

# ── 前提条件チェック ──────────────────────────────────────────
command -v uv   >/dev/null 2>&1 || error "uv が見つかりません。setup.sh を先に実行してください。"
command -v pnpm >/dev/null 2>&1 || error "pnpm が見つかりません。setup.sh を先に実行してください。"

# ── .env.local チェック ───────────────────────────────────────
if [ ! -f "$ROOT/.env.local" ]; then
  error ".env.local が見つかりません。setup.sh を先に実行してください。"
fi

# ── node_modules チェック ─────────────────────────────────────
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  error "node_modules が見つかりません。setup.sh を先に実行してください。"
fi

# ── 起動 ──────────────────────────────────────────────────────
info "バックエンドと Electron を起動しています..."
echo ""

cd "$ROOT/frontend"
exec pnpm dev
