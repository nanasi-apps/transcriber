#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$ROOT/.env.local"
ENV_EXAMPLE_FILE="$ROOT/.env.local.example"
CI_MODE=0

# ── 色付き出力 ────────────────────────────────────────────────
info()    { printf '\033[1;34m[INFO]\033[0m  %s\n' "$*"; }
success() { printf '\033[1;32m[OK]\033[0m    %s\n' "$*"; }
warn()    { printf '\033[1;33m[WARN]\033[0m  %s\n' "$*"; }
error()   { printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

first_line() {
  local text="$1"
  printf '%s\n' "${text%%$'\n'*}"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --ci|--non-interactive)
      CI_MODE=1
      ;;
    *)
      error "不明なオプションです: $1"
      ;;
  esac
  shift
done

install_homebrew_dependencies() {
  command -v brew >/dev/null 2>&1 || error "Homebrew が見つかりません。https://brew.sh からインストールしてください。"

  info "Homebrew の依存関係を確認しています..."
  if brew bundle check --no-upgrade --file="$ROOT/Brewfile" >/dev/null 2>&1; then
    success "Brewfile の依存関係はすでに揃っています。"
    return
  fi

  HOMEBREW_NO_AUTO_UPDATE="${HOMEBREW_NO_AUTO_UPDATE:-1}" brew bundle install --no-upgrade --file="$ROOT/Brewfile"
  success "Homebrew の依存関係をインストールしました。"
}

write_env_file() {
  local hf_token="$1"
  printf 'HF_TOKEN=%s\n' "$hf_token" > "$ENV_FILE"
}

# ── 前提条件チェック ──────────────────────────────────────────
install_homebrew_dependencies

info "前提条件を確認しています..."

command -v python3.13 >/dev/null 2>&1 || error "python3.13 が見つかりません。Brewfile のセットアップを確認してください。"
command -v uv         >/dev/null 2>&1 || error "uv が見つかりません。Brewfile のセットアップを確認してください。"
command -v pnpm       >/dev/null 2>&1 || error "pnpm が見つかりません。Brewfile のセットアップを確認してください。"
command -v ffmpeg     >/dev/null 2>&1 || error "ffmpeg が見つかりません。Brewfile のセットアップを確認してください。"

success "brew: $(first_line "$(brew --version)")"
success "python3.13: $(python3.13 --version 2>&1)"
success "uv: $(uv --version)"
success "pnpm: $(pnpm --version)"
success "ffmpeg: $(first_line "$(ffmpeg -version)")"

# ── .env.local の確認 ─────────────────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
  warn ".env.local が見つかりません。作成します。"

  if [ -n "${HF_TOKEN:-}" ]; then
    write_env_file "$HF_TOKEN"
    success "環境変数 HF_TOKEN から .env.local を作成しました。"
  elif [ "$CI_MODE" -eq 1 ] || [ -n "${CI:-}" ] || [ ! -t 0 ]; then
    if [ -f "$ENV_EXAMPLE_FILE" ]; then
      cp "$ENV_EXAMPLE_FILE" "$ENV_FILE"
    else
      write_env_file ""
    fi
    warn "HF_TOKEN は未設定のままです。必要になったら $ENV_FILE を編集してください。"
  else
    printf '\nHugging Face のアクセストークンが必要です。\n'
    printf '  取得先: https://huggingface.co/settings/tokens\n'
    printf '  モデルへのアクセス申請: https://huggingface.co/pyannote/speaker-diarization-3.1\n\n'
    read -rp "HF_TOKEN を入力してください: " hf_token

    if [ -z "$hf_token" ]; then
      if [ -f "$ENV_EXAMPLE_FILE" ]; then
        cp "$ENV_EXAMPLE_FILE" "$ENV_FILE"
      else
        write_env_file ""
      fi
      warn "HF_TOKEN が空です。後で $ENV_FILE に手動で設定してください。"
    else
      write_env_file "$hf_token"
      success ".env.local を作成しました。"
    fi
  fi
else
  success ".env.local が存在します。"
fi

# ── バックエンドのセットアップ ────────────────────────────────
info "バックエンドの依存関係をインストールしています..."
uv sync --project "$ROOT/backend" --python "$(command -v python3.13)"
success "バックエンドのセットアップ完了。"

# ── フロントエンドのセットアップ ──────────────────────────────
info "フロントエンドの依存関係をインストールしています..."
pnpm --dir "$ROOT/frontend" install --frozen-lockfile
success "フロントエンドのセットアップ完了。"

# ── 完了 ──────────────────────────────────────────────────────
printf '\n'
printf '\033[1;32m========================================\033[0m\n'
printf '\033[1;32m  セットアップが完了しました！\033[0m\n'
printf '\033[1;32m========================================\033[0m\n'
printf '\n'
printf '起動するには次のコマンドを実行してください:\n'
printf '  ./start.sh\n'
