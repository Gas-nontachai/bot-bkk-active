#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export UV_PYTHON_INSTALL_DIR="$project_dir/.api-capture/python"
export UV_CACHE_DIR="$project_dir/.api-capture/cache/uv"
if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.12 "$project_dir/.venv-api"
    uv pip install --python "$project_dir/.venv-api/bin/python" 'mitmproxy>=12,<13'
elif [ -n "${API_PYTHON:-}" ]; then
    "$API_PYTHON" -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ required"'
    "$API_PYTHON" -m venv "$project_dir/.venv-api"
    "$project_dir/.venv-api/bin/python" -m pip install 'mitmproxy>=12,<13'
else
    python3 -m venv "$project_dir/.api-capture/bootstrap"
    "$project_dir/.api-capture/bootstrap/bin/python" -m pip install \
        --cache-dir "$project_dir/.api-capture/cache/pip" uv
    "$project_dir/.api-capture/bootstrap/bin/uv" venv --python 3.12 "$project_dir/.venv-api"
    "$project_dir/.api-capture/bootstrap/bin/uv" pip install \
        --python "$project_dir/.venv-api/bin/python" 'mitmproxy>=12,<13'
fi
"$project_dir/.venv-api/bin/mitmdump" --version
