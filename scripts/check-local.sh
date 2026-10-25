#!/usr/bin/env bash
# Local regression checks only: no account, network API, commit, packaging or push.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pytest tests/ -q
cargo fmt --manifest-path desktop/src-tauri/Cargo.toml --check
cargo test --manifest-path desktop/src-tauri/Cargo.toml
cargo clippy --manifest-path desktop/src-tauri/Cargo.toml --all-targets -- -D warnings
(cd desktop && npm run build)
