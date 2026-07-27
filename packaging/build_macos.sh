#!/usr/bin/env bash
# macOS 실행 파일(.app) 빌드. macOS 에서 실행할 것.
set -euo pipefail

cd "$(dirname "$0")/.."     # 저장소 루트로 이동

python3 -m venv .buildvenv
# shellcheck disable=SC1091
source .buildvenv/bin/activate
pip install --upgrade pip
pip install -r packaging/requirements-build.txt

pyinstaller --noconfirm --clean build.spec

echo
echo "빌드 완료 → dist/UDP-Multicast-ECDIS.app"
echo "실행:  open dist/UDP-Multicast-ECDIS.app"
