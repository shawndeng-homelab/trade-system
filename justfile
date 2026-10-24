set dotenv-load := true
set shell := ["bash", "-euc"]
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

package_name := "options_strategies"
python_min_version := "3.12"
python_max_version := "3.14"
python_dev_version := python_min_version
pypi_server_url := "https://pypiserver.shawndeng.cc"

# Show available recipes
default:
    @just --list

# Sync workspace deps and install pre-commit hooks
init:
    uv tool install rust-just
    uv sync --all-packages --all-groups
    uvx pre-commit install

# Run ruff fix + format + check
lint:
    uvx ruff check --fix .
    uvx ruff format .
    uvx ruff check .

# Add `# noqa` for current violations, then re-run lint
lint-add-noqa: && lint-pre-commit lint
    uvx ruff check --add-noqa .

# Run all pre-commit hooks against the whole tree
lint-pre-commit:
    uvx pre-commit run --all-files

# Watch and re-run ruff on changes
lint-watch:
    uvx ruff check --watch .

# Run tests with the dev Python version
test:
    @just test-version {{python_dev_version}}

# Run tests across the configured Python version range
test-all:
    uv run python -c "import subprocess; mn=int('{{python_min_version}}'.split('.')[1]); mx=int('{{python_max_version}}'.split('.')[1]); [subprocess.check_call(['uv','run','--all-packages','--all-groups','--python',f'3.{m}','pytest','--cov={{package_name}}','--cov-report=xml','--cov-report=term-missing','-v','packages/']) for m in range(mn, mx + 1)]"

# Run tests for a specific Python version
test-version version:
    uv run --all-packages --all-groups --python {{version}} pytest --cov={{package_name}} --cov-report=xml --cov-report=term-missing -v packages/

# Serve docs locally
docs:
    uv run --all-packages --group docs mkdocs serve

# Build static docs
docs-build:
    uv run --all-packages --group docs mkdocs build

# Deploy docs to GitHub Pages
deploy-gh-pages:
    uv run --all-packages --group docs mkdocs gh-deploy --force

# Build sdist + wheel for every workspace package
build:
    uv build --all-packages

# Build only packages that have a new version tag (for CI)
build-changed:
    #!/usr/bin/env bash
    set -euo pipefail
    # Get the commit this workflow is running on
    commit=$(git rev-parse HEAD)
    built=0
    for pkg_dir in packages/*/; do
        pkg=$(basename "$pkg_dir")
        # Read version from pyproject.toml
        ver=$(grep '^version' "$pkg_dir/pyproject.toml" | head -1 | sed 's/version.*=.*"\(.*\)"/\1/')
        tag="${pkg}-${ver}"
        # Only build if the tag exists AND points to the current commit
        if tag_commit=$(git rev-parse "refs/tags/${tag}^{commit}" 2>/dev/null) && [ "$tag_commit" = "$commit" ]; then
            echo "✅ ${pkg} ${ver} has new tag at this commit, building..."
            uv build --package "$pkg"
            built=$((built + 1))
        else
            echo "⏭️  ${pkg} ${ver} tag not at this commit, skipping"
        fi
    done
    if [ "$built" -eq 0 ]; then
        echo "No changed packages to build"
    fi

# Publish to public PyPI (skips versions already on PyPI)
publish-pypi:
    uv publish --check-url https://pypi.org/simple/ dist/*

# Publish to the private PyPI server (skips versions already on the server)
publish-pypi-server:
    uv publish --check-url {{env_var_or_default('PYPI_SERVER_URL', pypi_server_url)}}/simple/ --username {{env_var('PYPI_SERVER_USERNAME')}} --password {{env_var('PYPI_SERVER_PASSWORD')}} --publish-url {{env_var_or_default('PYPI_SERVER_URL', pypi_server_url)}} dist/*

# Publish to both indexes
publish-all: publish-pypi publish-pypi-server

# Build then publish to public PyPI
deploy-pypi: build publish-pypi

# Build then publish to the private server
deploy-pypi-server: build publish-pypi-server

# Build then publish to both indexes
deploy-all: build publish-all

# Export pinned deps to requirements.txt
export-deps:
    uv export --no-hashes --output-file requirements.txt

# Download options data for a symbol (default: SPY)
download-options symbol="SPY":
    uv run optopsy-data download {{symbol}} -o -v

# Download stock data for a symbol (default: SPY)
download-stocks symbol="SPY":
    uv run optopsy-data download {{symbol}} -s -v

# Download both options and stock data for a symbol (default: SPY)
download symbol="SPY": (download-options symbol) (download-stocks symbol)

# 查看合成行情 CLI 的富文本帮助
sim-help:
    uv run --package options-strategies simulate-market --help

# 按配置生成合成行情，默认使用快速基线示例
sim-generate config="examples/simulation/baseline.json" output=".tmp/simulations/baseline":
    uv run --package options-strategies simulate-market generate --config {{quote(config)}} --output {{quote(output)}}

# 恢复相同配置的数据集，跳过已完成路径
sim-resume config="examples/simulation/baseline.json" output=".tmp/simulations/baseline":
    uv run --package options-strategies simulate-market generate --config {{quote(config)}} --output {{quote(output)}} --resume

# 校验文件摘要、行情边界和合约报价覆盖
sim-validate input=".tmp/simulations/baseline":
    uv run --package options-strategies simulate-market validate --input {{quote(input)}}

# 查看配置、生成版本和路径状态
sim-inspect input=".tmp/simulations/baseline":
    uv run --package options-strategies simulate-market inspect --input {{quote(input)}}

# 测量数据源耗时、峰值内存及落盘大小
sim-benchmark config="examples/simulation/baseline.json" output=".tmp/simulations/benchmark" paths="1":
    uv run --package options-strategies python scripts/benchmark_simulation.py --config {{quote(config)}} --output {{quote(output)}} --paths {{quote(paths)}}

# 运行合成行情的数据质量与 CLI 回归测试
sim-test:
    uv run --all-packages --group dev pytest -q packages/options-strategies/tests/test_simulation.py

# Add a new package to the workspace (skeleton + cog.toml + sync)
add-package name:
    uvx repo-scaffold@latest add-package {{name}}
