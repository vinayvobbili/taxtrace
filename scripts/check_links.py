"""Check every web link on the landing page, the README and docs/ (and the video files the page names).

    python scripts/check_links.py [ROOT]

Prints each link that doesn't answer with a success (after redirects) and exits 1 if there is one. Ko-fi and
LinkedIn refuse automated clients (403, 999), so they are skipped. Needs the network; the tests only check how
links are found.
"""

import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SKIPPED = ("ko-fi.com", "linkedin.com", "giscus.app")
URL = re.compile(r"""https?://[^\s)<>"'`\]]+""")
UA = "Mozilla/5.0 (link check)"


def links(root: Path) -> dict[str, list[str]]:
    """Each external URL, with the files that hold it."""
    found: dict[str, list[str]] = {}
    files = [root / "README.md", root / "site" / "index.html", *sorted((root / "docs").glob("*.md"))]
    for path in files:
        for url in URL.findall(path.read_text(encoding="utf-8")):
            url = url.rstrip(".,;:")
            if any(host in url for host in SKIPPED) or "{" in url or "localhost" in url or "127.0.0.1" in url:
                continue
            found.setdefault(url, [])
            if path.name not in found[url]:
                found[url].append(path.name)
    return found


def status(url: str) -> str:
    """"" when the link answers, else what went wrong."""
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(request, timeout=30):
                return ""
        except urllib.error.HTTPError as e:
            problem = f"HTTP {e.code}"
        except (OSError, ValueError) as e:
            problem = str(e)
    return problem


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent
    found = links(root)
    with ThreadPoolExecutor(8) as pool:
        results = dict(zip(found, pool.map(status, found), strict=True))
    bad = {url: why for url, why in results.items() if why}
    for url, why in bad.items():
        print(f"{why}: {url}  ({', '.join(found[url])})")
    print(f"{len(found)} links, {len(bad)} not answering")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
