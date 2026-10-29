import re
import shutil
import sys
import unicodedata
from collections import Counter
from datetime import date, datetime
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

import markdown
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

ROOT = Path(__file__).parent
CONTENT_DIR = ROOT / "content"
PAGES_DIR = CONTENT_DIR / "pages"
DEPARTMENTS_DIR = CONTENT_DIR / "departments"
STAFF_FILE = CONTENT_DIR / "staff.yaml"
TEMPLATES_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"
OUTPUT_DIR = ROOT / "dist"

SERVE_ADDRESS = ("localhost", 8000)

# `extra` is a bundle: md_in_html, tables, fenced_code, attr_list, def_list,
# abbr and footnotes. `footnotes` is named again so MARKDOWN_CONFIG can reach
# it -- config only applies to an extension listed explicitly.
MARKDOWN_EXTENSIONS = ["extra", "footnotes", "sane_lists", "smarty"]

MARKDOWN_CONFIG = {
    "footnotes": {"BACKLINK_TITLE": "Zpět na odkaz na poznámku {}"},
    "smarty": {
        "substitutions": {
            "left-double-quote": "&bdquo;",  # Czech quotes are „like this“
            "right-double-quote": "&ldquo;",
            "left-single-quote": "&sbquo;",
            "right-single-quote": "&lsquo;",
        }
    },
}

SITE = {
    "lang": "cs",
    "title": "Kryšpova univerzita",
    "description": "Kryšpova univerzita, Fakulta skotačení",
    "url": "https://kuni.hluchnikovi.cz",
}

DATE_FORMAT = "%Y.%m.%d"
DEFAULT_COLOR = "#ffc533"

env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)

# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def slugify(text: str) -> str:
    """'Čerstvý chléb' -> 'cerstvy-chleb'. URL-safe ASCII, nothing clever."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def format_date(value: date) -> str:
    return value.strftime(DATE_FORMAT)


env.filters["format_date"] = format_date


def split_front_matter(raw: str) -> tuple[dict, str]:
    """Split '---\\nyaml\\n---\\nbody' into (metadata, body). A file that only
    opens with a thematic break is returned untouched."""
    if not raw.startswith("---\n") or raw.count("---", 1) == 0:
        return {}, raw
    _, front_matter, body = raw.split("---", 2)
    return yaml.safe_load(front_matter) or {}, body.strip()


def render_markdown(body: str) -> str:
    return markdown.markdown(
        body, extensions=MARKDOWN_EXTENSIONS, extension_configs=MARKDOWN_CONFIG
    )


def read_markdown(path: Path) -> tuple[dict, str]:
    meta, body = split_front_matter(path.read_text(encoding="utf-8"))
    return meta, render_markdown(body)


def parse_post(path: Path, department_slug: str) -> dict:
    """One post file inside a department folder -> a post dict."""
    meta, content = read_markdown(path)
    missing = [key for key in ("title", "date") if key not in meta]
    if missing:
        raise ValueError(f"{path}: front matter is missing {', '.join(missing)}")

    # YAML turns an unquoted 2026-07-27 into a date already; a quoted one
    # arrives as a string.
    post_date = meta["date"]
    if isinstance(post_date, str):
        post_date = datetime.strptime(post_date, "%Y-%m-%d").date()
    if not isinstance(post_date, date):
        raise ValueError(f"{path}: 'date' must look like YYYY-MM-DD")

    slug = meta.get("slug") or slugify(meta["title"])
    return {
        "title": meta["title"],
        "date": post_date,
        "summary": meta.get("summary", ""),
        "info": meta.get("info") or [],
        "slug": slug,
        "url": f"/departments/{department_slug}/{slug}/",
        "content": content,
    }


def parse_page(path: Path) -> dict:
    """One file in content/pages/ -> a page dict."""
    meta, content = read_markdown(path)
    slug = meta.get("slug") or path.stem
    return {
        "title": meta.get("title", slug),
        "slug": slug,
        "url": f"/{slug}/",
        "content": content,
    }


def load_department(folder: Path) -> dict:
    """content/departments/<slug>/: index.md describes the department, every
    other .md file in the folder is one of its posts (newest first)."""
    slug = folder.name
    meta, content = read_markdown(folder / "index.md")
    posts = [
        parse_post(path, slug) for path in sorted(folder.glob("*.md")) if path.name != "index.md"
    ]
    posts.sort(key=lambda post: (post["date"], post["slug"]), reverse=True)

    clashes = [s for s, n in Counter(p["slug"] for p in posts).items() if n > 1]
    if clashes:
        raise ValueError(f"{folder}: two posts share a slug: {', '.join(sorted(clashes))}")

    return {
        "slug": slug,
        "title": meta.get("title", slug),
        "summary": meta.get("summary", ""),
        "emoji": meta.get("emoji", ""),
        "color": meta.get("color", DEFAULT_COLOR),
        "url": f"/departments/{slug}/",
        "content": content,
        "posts": posts,
    }


def load_departments() -> list[dict]:
    return [
        load_department(folder)
        for folder in sorted(DEPARTMENTS_DIR.iterdir())
        if (folder / "index.md").exists()
    ]


def load_staff(departments: list[dict]) -> list[dict]:
    """content/staff.yaml, in the order written. `department` is optional."""
    by_slug = {d["slug"]: d for d in departments}
    staff = yaml.safe_load(STAFF_FILE.read_text(encoding="utf-8")) or []
    for person in staff:
        slug = person.get("department")
        if slug and slug not in by_slug:
            raise ValueError(f"{STAFF_FILE}: {person['name']} has unknown department '{slug}'")
        person["department"] = by_slug.get(slug)
    return staff


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def render(template_name: str, url: str, **context) -> None:
    """Render a template to dist/<url>/index.html (or dist/<url> for a file)."""
    out_path = OUTPUT_DIR / url.strip("/")
    if not out_path.suffix:
        out_path /= "index.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        env.get_template(template_name).render(
            site=SITE, current_year=date.today().year, **context
        ),
        encoding="utf-8",
    )


def build() -> None:
    # Parse before deleting dist/, so a broken post leaves the previous build
    # in place instead of an empty directory.
    pages = [parse_page(path) for path in sorted(PAGES_DIR.glob("*.md"))]
    departments = load_departments()
    staff = load_staff(departments)

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)

    render("home.html", "/", departments=departments)
    render("staff.html", "/staff/", staff=staff)

    for department in departments:
        render("department.html", department["url"], department=department)
        for post in department["posts"]:
            render("post.html", post["url"], post=post, department=department)

    for page in pages:
        render("page.html", page["url"], page=page)

    # GitHub Pages serves /404.html for any path it cannot match.
    render("404.html", "/404.html")

    if STATIC_DIR.exists():
        shutil.copytree(STATIC_DIR, OUTPUT_DIR / "static")

    (OUTPUT_DIR / "CNAME").write_text(urlparse(SITE["url"]).netloc + "\n", encoding="utf-8")

    post_count = sum(len(d["posts"]) for d in departments)
    print(f"Built {len(departments)} department(s), {post_count} post(s), {len(pages)} page(s).")


def serve() -> None:
    handler = partial(SimpleHTTPRequestHandler, directory=str(OUTPUT_DIR))
    print("Serving http://{}:{} (Ctrl+C to stop)".format(*SERVE_ADDRESS))
    try:
        HTTPServer(SERVE_ADDRESS, handler).serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    build()
    if "--serve" in sys.argv:
        serve()
