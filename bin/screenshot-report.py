#!/usr/bin/env python3
"""Validate an evidence manifest and render a private, offline screenshot review."""
import argparse
import base64
from collections import Counter
from html import escape
import json
from pathlib import Path
import re
import sys

CAPTURE = {'captured', 'blocked', 'not-run', 'not-applicable'}
REVIEW = {'not-reviewed', 'pass', 'finding'}


def require_text(obj, key):
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{key}: expected nonempty text')
    return value


def text_list(obj, key, nonempty=False):
    value = obj.get(key)
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f'{key}: expected a list of text')
    if any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError(f'{key}: expected nonempty text entries')
    return value


def asset(root, name, kind, budget):
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError(f'{kind}: expected a relative local asset path')
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f'{kind}: missing asset or path outside manifest directory: {name}')
    if path.stat().st_size > 100 * 1024 * 1024:
        raise ValueError(f'{kind}: asset exceeds 100 MiB: {name}')
    budget[0] += path.stat().st_size
    if budget[0] > 256 * 1024 * 1024:
        raise ValueError("assets: aggregate exceeds 256 MiB; split into explicitly scoped reports")
    data = path.read_bytes()
    signatures = {
        'image': [('image/png', data.startswith(b'\x89PNG\r\n\x1a\n')),
                  ('image/jpeg', data.startswith(b'\xff\xd8\xff')),
                  ('image/webp', data[:4] == b'RIFF' and data[8:12] == b'WEBP')],
        'video': [('video/mp4', data[4:8] == b'ftyp'),
                  ('video/webm', data.startswith(b'\x1aE\xdf\xa3'))],
        'trace': [('application/zip', data.startswith(b'PK\x03\x04'))],
    }
    mime = next((mime for mime, valid in signatures[kind] if valid), None)
    if not mime:
        raise ValueError(f'{kind}: unsupported asset bytes: {name}')
    return f'data:{mime};base64,' + base64.b64encode(data).decode('ascii')


def validate(doc, root):
    if not isinstance(doc, dict) or type(doc.get('schemaVersion')) is not int or doc['schemaVersion'] != 1:
        raise ValueError('schemaVersion: expected 1')
    for key in ('title', 'scope', 'coverageStrategy'):
        require_text(doc, key)
    text_list(doc, 'exclusions')
    run = doc.get('run')
    if not isinstance(run, dict):
        raise ValueError('run: expected provenance object')
    for key in ('revision', 'dirtyFingerprint', 'timestamp', 'environment', 'dataMode'):
        require_text(run, key)
    columns = doc.get('columns')
    if not isinstance(columns, list) or not columns:
        raise ValueError('columns: expected an ordered list of {id, label} platform or size columns')
    column_ids = []
    for column in columns:
        if not isinstance(column, dict):
            raise ValueError('columns: expected {id, label} objects')
        cid = require_text(column, 'id')
        require_text(column, 'label')
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]*', cid) or cid in column_ids:
            raise ValueError(f'columns: duplicate or unsafe column id: {cid}')
        column_ids.append(cid)
    cases = doc.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('cases: expected at least one case, including unrun requirements')
    ids, evidence, budget, cells = set(), {}, [0], set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError('case: expected object')
        ident = require_text(case, 'id')
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]*', ident) or ident in ids:
            raise ValueError(f'id: duplicate or unsafe case id: {ident}')
        ids.add(ident)
        for key in ('point', 'surface', 'route', 'account', 'variant', 'expected', 'observed',
                    'nextAction', 'browser', 'theme', 'locale', 'deviceMode'):
            require_text(case, key)
        if case.get('column') not in column_ids:
            raise ValueError(f'{ident}: column must be one of the declared column ids: {column_ids}')
        cells.add((case['point'], case['column']))
        text_list(case, 'conditions', True)
        text_list(case, 'steps', True)
        viewport = case.get('viewport')
        if not isinstance(viewport, dict) or any(
            type(viewport.get(k)) not in (int, float) or not 0 < viewport[k] < 100000
            for k in ('width', 'height', 'dpr')
        ):
            raise ValueError(f'{ident}: viewport needs positive width, height and dpr')
        if (not isinstance(case.get('captureStatus'), str) or
                not isinstance(case.get('reviewStatus'), str) or
                case['captureStatus'] not in CAPTURE or case['reviewStatus'] not in REVIEW):
            raise ValueError(f'{ident}: unknown captureStatus or reviewStatus')
        captured = case['captureStatus'] == 'captured'
        if not captured:
            require_text(case, 'reason')
            if case['reviewStatus'] != 'not-reviewed' or case.get('image'):
                raise ValueError(f'{ident}: uncaptured case cannot have image or review verdict')
        elif not case.get('image'):
            raise ValueError(f'{ident}: captured case requires image')
        evidence[ident] = {kind: asset(root, case[kind], kind, budget)
                           for kind in ('image', 'video', 'trace') if case.get(kind)}
    for point in dict.fromkeys(c['point'] for c in cases):
        for cid in column_ids:
            if (point, cid) not in cells:
                raise ValueError(f'point "{point}": no case for column {cid}; add a case with its '
                                 'status (not-run, blocked or not-applicable) and reason')
    return evidence


def render(doc, root):
    evidence = validate(doc, root)
    e = lambda value: escape(str(value), quote=True)
    cases = doc['cases']
    columns = doc['columns']
    points = list(dict.fromkeys(c['point'] for c in cases))
    cells = {}
    for c in cases:
        cells.setdefault((c['point'], c['column']), []).append(c)
    row_id = {p: f'point-{i + 1}' for i, p in enumerate(points)}
    captures = Counter(c['captureStatus'] for c in cases)
    reviews = Counter(c['reviewStatus'] for c in cases)
    summary = ' · '.join([f'{len(points)} point' + ('' if len(points) == 1 else 's'), f'{len(cases)} cases'] +
                         [f'{captures[k]} {k}' for k in sorted(CAPTURE)] +
                         [f'{reviews[k]} {k}' for k in sorted(REVIEW)])
    head = ''.join(f'<th>{e(col["label"])}</th>' for col in columns)
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; media-src data:; style-src \'unsafe-inline\'">',
             f'<title>{e(doc["title"])}</title>',
             '<style>body{font:16px/1.5 system-ui,sans-serif;margin:0 auto;padding:24px;max-width:1800px;color:#222;background:#fff}h1{font-size:28px}h2{font-size:22px}h3{font-size:16px;margin:0 0 6px}a{color:#174c99}table{border-collapse:collapse;width:100%}table.summary{min-width:1000px}table.gallery{table-layout:fixed}.point-block{margin-top:32px}.point-block>h2{margin-bottom:6px}.point-block>p{margin-top:0}td,th{border:1px solid #bbb;padding:8px;text-align:left;vertical-align:top}th.point,td.point{min-width:180px;max-width:240px}img,video{display:block;max-width:100%;height:auto}img.narrow,video.narrow{max-width:300px}p,li,td{overflow-wrap:anywhere}.table{overflow-x:auto;margin-top:16px}.case{border-top:2px solid #aaa;margin-top:14px;padding-top:10px}.case:first-child{border-top:0;margin-top:0;padding-top:0}.conditions{background:#f3f4f6;padding:8px}.conditions ul{margin:4px 0;padding-left:18px}dt{font-weight:600}dd{margin:0 0 10px}pre{white-space:pre-wrap}</style>',
             f'<h1>{e(doc["title"])}</h1><p><strong>{e(summary)}</strong></p>',
             '<p>Capture counts describe evidence, not approval. Review verdicts are supplied by the reviewer.</p>',
             f'<p><b>Scope:</b> {e(doc["scope"])}</p><p><b>Coverage:</b> {e(doc["coverageStrategy"])}</p>',
             '<p><b>Exclusions:</b> ' + e('; '.join(doc['exclusions']) or 'None declared') + '</p>',
             '<details><summary>Run provenance</summary><p>' + e(' · '.join(f'{k}: {v}' for k, v in doc['run'].items())) + '</p></details>',
             f'<div class="table"><table class="summary"><thead><tr><th class="point">Point</th>{head}<th>Next actions</th></tr></thead><tbody>']
    for point in points:
        row = [f'<tr><td class="point"><a href="#{row_id[point]}">{e(point)}</a></td>']
        actions = []
        for col in columns:
            group = cells[(point, col['id'])]
            row.append('<td>' + '<br>'.join(
                f'<a href="#{e(c["id"])}">{e(c["captureStatus"])} / {e(c["reviewStatus"])}</a>' for c in group) + '</td>')
            actions.extend(f'{col["label"]}: {c["nextAction"]}' for c in group)
        row.append('<td>' + '<br>'.join(e(a) for a in actions) + '</td></tr>')
        parts.extend(row)
    parts.append('</tbody></table></div>')
    for point in points:
        surfaces = '; '.join(dict.fromkeys(c['surface'] for c in cases if c['point'] == point))
        parts.append(f'<section id="{row_id[point]}" class="point-block"><h2>{e(point)}</h2><p>{e(surfaces)}</p>')
        parts.append(f'<div class="table"><table class="gallery" style="min-width:{len(columns) * 320}px"><thead><tr>{head}</tr></thead><tbody><tr>')
        for col in columns:
            parts.append('<td>')
            for c in cells[(point, col['id'])]:
                v = c['viewport']
                narrow = ' class="narrow"' if v['width'] <= 500 else ''
                parts.append(f'<section id="{e(c["id"])}" class="case"><h3>{e(c["id"])}</h3><div class="conditions"><b>Conditions</b><ul>')
                parts.extend(f'<li>{e(x)}</li>' for x in c['conditions'])
                parts.append(f'</ul><p><b>Where:</b> {e(c["route"])} · <b>Account:</b> {e(c["account"])} · <b>Viewport:</b> {e(v["width"])} × {e(v["height"])} @ {e(v["dpr"])} · <b>Variant:</b> {e(c["variant"])}</p>')
                parts.append('<details><summary>Reproduction and capture details</summary><p>' + e(' · '.join(f'{k}: {c[k]}' for k in ('browser', 'theme', 'locale', 'deviceMode'))) + '</p>')
                parts.append('<b>Reproduce</b><ol>')
                parts.extend(f'<li>{e(x)}</li>' for x in c['steps'])
                parts.append(f'</ol></details><p><b>Expected:</b> {e(c["expected"])}</p><p><b>Observed:</b> {e(c["observed"])}</p><p><b>Status:</b> {e(c["captureStatus"])} / {e(c["reviewStatus"])}</p><p><b>Next action:</b> {e(c["nextAction"])}</p></div>')
                assets = evidence[c['id']]
                if 'image' in assets:
                    parts.append(f'<img{narrow} src="{assets["image"]}" alt="{e(c["point"])}: {e(c["id"])}">')
                else:
                    parts.append(f'<p><b>Evidence gap:</b> {e(c["reason"])}</p>')
                if 'video' in assets:
                    parts.append(f'<video{narrow} controls preload="metadata" src="{assets["video"]}"></video>')
                if 'trace' in assets:
                    parts.append(f'<p><a download="{e(c["id"])}-trace.zip" href="{assets["trace"]}">Download investigation trace</a></p>')
                parts.append('</section>')
            parts.append('</td>')
        parts.append('</tr></tbody></table></div></section>')
    return ''.join(parts) + '</html>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.manifest.resolve() == args.output.resolve():
            raise ValueError('output must differ from manifest')
        doc = json.loads(args.manifest.read_text())
        html = render(doc, args.manifest.parent)
        for case in doc['cases']:
            for kind in ('image', 'video', 'trace'):
                if case.get(kind) and (args.manifest.parent / case[kind]).resolve() == args.output.resolve():
                    raise ValueError('output must not overwrite an evidence asset')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(html, encoding='utf-8')
    except (ValueError, OSError, TypeError) as exc:
        parser.exit(2, f'screenshot-report: {exc}\n')
    print(args.output.resolve())


if __name__ == '__main__':
    main()
