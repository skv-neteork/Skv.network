"""T88 site checks. Reads files only. Does not start or call the production API."""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "app"
NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _text(path):
    return path.read_text(encoding="utf-8")


def _sitemap_paths(xml_text):
    root = ET.fromstring(xml_text)
    locs = [el.text.strip() for el in root.findall("sm:url/sm:loc", NS)]
    return [re.sub(r"^https://skv\.network", "", loc) or "/" for loc in locs]


def _robots_disallow(text):
    return [line.split(":", 1)[1].strip() for line in text.splitlines() if line.lower().startswith("disallow:")]


def test_hero_is_permanent_memory_and_connects():
    home = _text(APP / "home.html")
    assert "social network" not in home.lower()
    assert "<h1>Permanent memory for AI agents</h1>" in home
    assert "It works across models and agents, and is built for years with an agent, not a short project." in home
    hero = home.split('<section class="hero">', 1)[1].split("</section>", 1)[0]
    # One subtitle paragraph, then the buttons. The demo note sits under the buttons.
    assert hero.count("<h1>") == 1
    assert 'href="/connect" class="btn btn-purple">Connect</a>' in hero
    assert hero.index("btn-purple") < hero.index("btn-gray")
    fallback = _text(APP / "main.py")
    assert "a social network for AI agents" not in fallback
    assert 'href="/connect">Connect</a>' in fallback


def test_footers_use_skv_address():
    for name in ("profile.html", "security.html", "support.html"):
        text = _text(APP / name)
        footers = re.findall(r"<footer[\s\S]*?</footer>", text, flags=re.I)
        assert footers, name
        blob = "\n".join(footers)
        assert "denizchavdarov" not in blob, name
        assert "mailto:noreply@skv.network" in blob, name


def test_sitemap_robots_llms_agree():
    sm = _text(APP / "downloads" / "sitemap.xml")
    robots = _text(APP / "downloads" / "robots.txt")
    llms = _text(APP / "downloads" / "llms.txt")
    paths = _sitemap_paths(sm)
    disallow = set(_robots_disallow(robots))
    assert paths
    assert not (set(paths) & disallow)
    for path in paths:
        assert path in llms, path
    assert "social network" not in llms.lower()
    assert "Sitemap: https://skv.network/sitemap.xml" in robots
    # Stale repo copies must match the files the app serves.
    assert _text(ROOT / "src" / "downloads" / "sitemap.xml") == sm
    assert _text(ROOT / "src" / "downloads" / "robots.txt") == robots
    main = _text(APP / "main.py")
    assert 'os.path.join(os.path.dirname(__file__), "downloads", "sitemap.xml")' in main
    pages = _text(APP / "routers" / "pages.py")
    assert 'return RedirectResponse(url="/about", status_code=301)' in pages


def test_files_served_with_200():
    """The API reads these files from the bind mount. GET only, no restart."""
    import urllib.request

    def get(path):
        req = urllib.request.Request("http://127.0.0.1:8000" + path, headers={"Host": "skv.network"})
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, response.read()

    for path in ("/", "/sitemap.xml", "/robots.txt", "/llms.txt", "/connect", "/security", "/support", "/profile"):
        status, body = get(path)
        assert status == 200, path
        assert body, path
    home_status, home = get("/")
    assert home_status == 200
    assert b"Permanent memory for AI agents" in home
    assert b"social network" not in home.lower()
    assert b'href="/connect"' in home
    sm_status, sm = get("/sitemap.xml")
    assert sm_status == 200
    assert b"<loc>https://skv.network/connect</loc>" in sm
    llms_status, llms = get("/llms.txt")
    assert llms_status == 200
    assert b"Permanent memory for AI agents" in llms
    for page in ("/security", "/support", "/profile"):
        status, body = get(page)
        assert status == 200
        assert b"mailto:noreply@skv.network" in body, page


if __name__ == "__main__":
    import traceback
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception:
                failed += 1
                print("FAIL", name)
                traceback.print_exc()
    raise SystemExit(failed)
