#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$(dirname "$(realpath "$0")")")"
python_bin="${PYTHON:-python}"
"$python_bin" -m PyInstaller --noconfirm --clean desktop/payroll.spec
