"""scripts/check_links.py: finds the web links in the page, README and docs, and skips what refuses robots."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_links.py"
spec = importlib.util.spec_from_file_location("check_links", SCRIPT)
check_links = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_links)


def test_links_found_in_each_file_and_robot_blockers_skipped(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "site").mkdir()
    (tmp_path / "README.md").write_text(
        "See [uv](https://docs.astral.sh/uv/). Coffee: https://ko-fi.com/someone, http://127.0.0.1:8010/v1.\n")
    (tmp_path / "site" / "index.html").write_text(
        '<a href="https://docs.astral.sh/uv/">x</a> <a href="https://www.linkedin.com/in/someone/">y</a>')
    (tmp_path / "docs" / "a.md").write_text("[IRS](https://www.irs.gov/forms), see https://example.org/x.\n")
    found = check_links.links(tmp_path)
    assert found == {
        "https://docs.astral.sh/uv/": ["README.md", "index.html"],
        "https://www.irs.gov/forms": ["a.md"],
        "https://example.org/x": ["a.md"],
    }
