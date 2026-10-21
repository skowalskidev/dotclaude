"""Compose artifact adapters into the one offline presentation frame."""
import html
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC_TAG_OPEN = '<script id="spec" type="application/json">'
# Capture asset token, the one Python definition. bin/mockup-shell.html declares the same
# literal as ASSET_TOKEN for the viewer; bin/mockup-shell.test.py asserts the two are identical.
ASSET_TOKEN = r"@@ASSET:([A-Za-z0-9_]+)@@"
ASSET_RE = re.compile(ASSET_TOKEN)


def resolve_assets(capture: str, assets: dict) -> str:
    """Fill asset tokens exactly as the viewer does: an unknown or empty id renders as ''."""
    return ASSET_RE.sub(lambda match: assets.get(match[1]) or "", capture)


def missing_assets(capture: str, assets: dict) -> list:
    """Asset ids a capture references that spec.assets does not supply."""
    return sorted({key for key in ASSET_RE.findall(capture) if not assets.get(key)})


def embed(spec: dict) -> str:
    return json.dumps(spec, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def compose(kind: str, spec: dict, adapter: str, *, content: str = "", title: str = "") -> str:
    """Adapters provide scoped styles and a renderer; frame structure lives here once."""
    shell = (HERE / "presentation-shell.html").read_text(encoding="utf-8")
    style, script = adapter.split("<!--ADAPTER_SCRIPT-->", 1)
    values = {"KIND": kind, "TITLE": html.escape(title), "ADAPTER_STYLE": style,
              "CONTENT": content, "ADAPTER_SCRIPT": script, "SPEC": embed(spec)}
    # One pass prevents a spec's literal placeholder strings becoming template syntax.
    return re.sub(r"@@(KIND|TITLE|ADAPTER_STYLE|CONTENT|ADAPTER_SCRIPT|SPEC)@@",
                  lambda match: values[match[1]], shell)


def extract(page: str) -> dict:
    match = re.search(r'<script\b(?=[^>]*\bid=["\']spec["\'])(?=[^>]*\btype=["\']application/json["\'])[^>]*>(.*?)</script>', page, re.S)
    if not match:
        raise ValueError("No #spec JSON data island")
    return json.loads(match[1])
