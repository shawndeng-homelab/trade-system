"""从 README 生成站点首页."""

from pathlib import Path

import mkdocs_gen_files


readme_path = Path(__file__).resolve().parents[1] / "README.md"
content = readme_path.read_text(encoding="utf-8")
# README 的链接从仓库根目录解析；站点首页已经位于 docs 根目录。
content = content.replace("](docs/", "](")

with mkdocs_gen_files.open("index.md", "w") as f:
    f.write(content)
