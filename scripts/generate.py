#!/usr/bin/env python3
"""Regenerate the profile SVG assets and README from live GitHub data.

Stdlib only. Needs GH_TOKEN (or GITHUB_TOKEN) with read access to public data.
Offline iteration: set PROFILE_JSON=/path/to/saved.json to skip the network.
Public repositories only: nothing private is ever queried or rendered.
"""
import datetime as dt
import html
import json
import os
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

# Palette lifted from devkim.me so the profile and the portfolio read as one brand.
INK, PANEL, RAISED = "#0e0f0d", "#12140f", "#171916"
CREAM, SOFT, MUTE = "#fbf7e6", "#c9c5b1", "#9a9786"
CORAL, AQUA, IRIS, VOLT, BLUSH = "#ff6a3d", "#45e3d0", "#9b8cff", "#d7ff3f", "#ffaee8"
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"

QUERY = """
query($login:String!){
  user(login:$login){
    login name createdAt
    followers{totalCount}
    contributionsCollection{
      totalPullRequestContributions
      totalCommitContributions
      contributionCalendar{ totalContributions weeks{ contributionDays{ date contributionCount weekday } } }
    }
    repositories(privacy:PUBLIC, ownerAffiliations:OWNER, isFork:false, first:100, orderBy:{field:PUSHED_AT, direction:DESC}){
      totalCount
      nodes{
        name description url homepageUrl stargazerCount pushedAt isArchived
        primaryLanguage{ name color }
        languages(first:10, orderBy:{field:SIZE, direction:DESC}){ edges{ size node{ name color } } }
        defaultBranchRef{ target{ ... on Commit{ history(first:8){ nodes{ messageHeadline committedDate } } } } }
      }
    }
    everything: repositories(privacy:PUBLIC, ownerAffiliations:OWNER){ totalCount }
  }
}
"""


def esc(s):
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------- data


def fetch():
    cached = os.environ.get("PROFILE_JSON")
    if cached:
        return json.loads(pathlib.Path(cached).read_text())["data"]["user"]
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GH_TOKEN or GITHUB_TOKEN is required")
    body = json.dumps({"query": QUERY, "variables": {"login": CFG["login"]}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={"Authorization": "bearer " + token, "User-Agent": "dwk601-profile"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.load(r)
    if payload.get("errors"):
        sys.exit("GraphQL errors: %s" % payload["errors"])
    return payload["data"]["user"]


def derive(u):
    cal = u["contributionsCollection"]["contributionCalendar"]
    days = sorted(
        (d for w in cal["weeks"] for d in w["contributionDays"]), key=lambda d: d["date"]
    )
    counts = [d["contributionCount"] for d in days]
    longest = run = 0
    for c in counts:
        run = run + 1 if c else 0
        longest = max(longest, run)
    # Current streak: today may still be empty, so start from yesterday in that case.
    i = len(counts) - 1
    if i >= 0 and counts[i] == 0:
        i -= 1
    current = 0
    while i >= 0 and counts[i] > 0:
        current += 1
        i -= 1
    repos = [r for r in u["repositories"]["nodes"] if not r["isArchived"]]
    totals, colors = {}, {}
    for r in u["repositories"]["nodes"]:
        for e in r["languages"]["edges"]:
            n = e["node"]["name"]
            totals[n] = totals.get(n, 0) + e["size"]
            colors[n] = e["node"]["color"] or MUTE
    return {
        "weeks": cal["weeks"],
        "total": cal["totalContributions"],
        "active_days": sum(1 for c in counts if c),
        "last30": sum(counts[-30:]),
        "n_days": len(counts),
        "streak": current,
        "longest": longest,
        "prs": u["contributionsCollection"]["totalPullRequestContributions"],
        "public_repos": u["everything"]["totalCount"],
        "originals": u["repositories"]["totalCount"],
        "repos": repos,
        "by_name": {r["name"]: r for r in u["repositories"]["nodes"]},
        "lang_totals": totals,
        "lang_colors": colors,
        "since": int(u["createdAt"][:4]),
    }


def ago(iso):
    t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    s = (dt.datetime.now(dt.timezone.utc) - t).total_seconds()
    if s < 3600:
        return "just now"
    if s < 86400:
        return "%dh ago" % (s // 3600)
    d = int(s // 86400)
    if d < 14:
        return "%dd ago" % d
    if d < 60:
        return "%dw ago" % (d // 7)
    return t.strftime("%b %Y")


def short_date(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%b %d").replace(" 0", " ")


# ---------------------------------------------------------------- svg helpers


def svg(w, h, body, title, desc="", defs="", style=""):
    base = (
        "text{font-family:%s}.m{font-family:%s}"
        "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"
    ) % (SANS, MONO)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
        'fill="none" role="img" aria-labelledby="t d">\n'
        '<title id="t">%s</title><desc id="d">%s</desc>\n'
        "<defs>%s</defs>\n<style>%s%s</style>\n%s\n</svg>\n"
    ) % (w, h, w, h, esc(title), esc(desc), defs, base, style, body)


def write(name, content):
    ASSETS.mkdir(exist_ok=True)
    (ASSETS / name).write_text(content, encoding="utf-8")


def wrap(text, width, max_lines):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if len(t) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while len(last) > width - 1:
            last = last.rsplit(" ", 1)[0]
        lines[-1] = last.rstrip(" .,;:") + "\u2026"
    return lines


def panel(w, h, r=18, extra=""):
    return (
        '<rect x="0.5" y="0.5" width="%d" height="%d" rx="%d" fill="%s" stroke="#fbf7e6" '
        'stroke-opacity=".09" %s/>' % (w - 1, h - 1, r, PANEL, extra)
    )


# ---------------------------------------------------------------- header


def typed_block(phrases, x0, y, charw, size, per=5.0, type_t=1.7, hold=4.5):
    total = per * len(phrases)
    texts, clips, cursor = [], [], [(0.0, x0)]
    for i, ph in enumerate(phrases):
        n, start = len(ph), i * per
        times, widths = [0.0], [0]
        for k in range(1, n + 1):
            times.append(start + type_t * k / n)
            widths.append(round(k * charw, 2))
            cursor.append((start + type_t * k / n, x0 + k * charw))
        times.append(start + hold)
        widths.append(0)
        cursor.append((start + hold, x0))
        kt = ";".join("%.5f" % (t / total) for t in times)
        vs = ";".join(str(w) for w in widths)
        clips.append(
            '<clipPath id="c%d"><rect x="%s" y="%s" height="%d" width="0">'
            '<animate attributeName="width" calcMode="discrete" dur="%ss" repeatCount="indefinite" '
            'keyTimes="%s" values="%s"/></rect></clipPath>'
            % (i, x0, y - size, size + 8, total, kt, vs)
        )
        texts.append(
            '<text class="m" x="%s" y="%s" font-size="%s" fill="%s" textLength="%s" '
            'lengthAdjust="spacing" clip-path="url(#c%d)">%s</text>'
            % (x0, y, size, AQUA, round(n * charw, 2), i, esc(ph))
        )
    ckt = ";".join("%.5f" % (t / total) for t, _ in cursor)
    cvs = ";".join(str(round(x, 2)) for _, x in cursor)
    cur = (
        '<rect y="%s" width="9" height="%d" rx="1.5" fill="%s" x="%s">'
        '<animate attributeName="x" calcMode="discrete" dur="%ss" repeatCount="indefinite" '
        'keyTimes="%s" values="%s"/>'
        '<animate attributeName="opacity" calcMode="discrete" dur="1s" repeatCount="indefinite" '
        'keyTimes="0;.5" values="1;0"/></rect>'
        % (y - size + 1, size + 2, CORAL, x0, total, ckt, cvs)
    )
    return "".join(clips), "".join(texts) + cur


def build_header():
    W, H = 900, 300
    cx, cy = 752, 150
    clips, typed = typed_block(CFG["typed"], 70, 238, 9.6, 16)
    defs = (
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#151712"/>'
        '<stop offset="1" stop-color="%s"/></linearGradient>'
        '<filter id="blur" x="-50%%" y="-50%%" width="200%%" height="200%%"><feGaussianBlur stdDeviation="46"/></filter>'
        '<pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse">'
        '<circle cx="1.5" cy="1.5" r="1" fill="%s" fill-opacity=".16"/></pattern>'
        '<linearGradient id="fade" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity=".05"/>'
        '<stop offset=".55" stop-color="#fff" stop-opacity=".55"/><stop offset="1" stop-color="#fff"/></linearGradient>'
        '<mask id="dm"><rect width="%d" height="%d" fill="url(#fade)"/></mask>'
        '<linearGradient id="nm" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="%s"/><stop offset="1" stop-color="#ff9a5c"/></linearGradient>'
        '<clipPath id="round"><rect width="%d" height="%d" rx="22"/></clipPath>'
        '<radialGradient id="core" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="%s" stop-opacity=".45"/>'
        '<stop offset="1" stop-color="%s" stop-opacity="0"/></radialGradient>'
        % (INK, CREAM, W, H, CORAL, W, H, CORAL, CORAL)
        + clips
    )
    blobs = (
        '<g filter="url(#blur)">'
        '<circle cx="770" cy="70" r="120" fill="%s" fill-opacity=".50"><animate attributeName="cx" values="770;700;790;770" dur="16s" repeatCount="indefinite"/>'
        '<animate attributeName="cy" values="70;120;60;70" dur="16s" repeatCount="indefinite"/></circle>'
        '<circle cx="640" cy="260" r="110" fill="%s" fill-opacity=".32"><animate attributeName="cx" values="640;700;610;640" dur="19s" repeatCount="indefinite"/>'
        '<animate attributeName="cy" values="260;230;280;260" dur="19s" repeatCount="indefinite"/></circle>'
        '<circle cx="880" cy="250" r="90" fill="%s" fill-opacity=".22"><animate attributeName="cx" values="880;840;890;880" dur="22s" repeatCount="indefinite"/></circle>'
        "</g>" % (CORAL, IRIS, AQUA)
    )

    def orbit(r, stroke, op, dash, dur, rev, node_col, node_r, extra=""):
        a, b = (360, 0) if rev else (0, 360)
        return (
            '<g><circle cx="%d" cy="%d" r="%d" stroke="%s" stroke-opacity="%s" %s/>'
            '<g><circle cx="%d" cy="%d" r="%s" fill="%s"/>%s'
            '<animateTransform attributeName="transform" type="rotate" from="%d %d %d" to="%d %d %d" dur="%ss" repeatCount="indefinite"/></g></g>'
            % (cx, cy, r, stroke, op, dash, cx + r, cy, node_r, node_col, extra, a, cx, cy, b, cx, cy, dur)
        )

    orbits = (
        orbit(54, CORAL, ".6", 'stroke-dasharray="3 7"', 22, False, CORAL, 4.5)
        + orbit(88, CREAM, ".14", "", 30, True, AQUA, 5, '<circle cx="%d" cy="%d" r="3" fill="%s"/>' % (cx - 88, cy, IRIS))
        + orbit(122, IRIS, ".38", 'stroke-dasharray="2 9"', 46, False, IRIS, 4)
    )
    core = (
        '<circle cx="%d" cy="%d" r="62" fill="url(#core)"/>'
        '<rect x="%d" y="%d" width="56" height="56" rx="16" fill="%s" stroke="%s" stroke-opacity=".9" stroke-width="1.5"/>'
        '<text class="m" x="%d" y="%d" font-size="15" font-weight="700" fill="%s" text-anchor="middle" letter-spacing="1">DWK</text>'
        % (cx, cy, cx - 28, cy - 28, RAISED, CORAL, cx, cy + 5, CORAL)
    )
    left = (
        '<text class="m" x="44" y="64" font-size="12" font-weight="600" fill="%s" letter-spacing="2.2">%s</text>'
        '<text x="42" y="146" font-size="76" font-weight="800" letter-spacing="-2.5" fill="%s">Dongwook <tspan fill="url(#nm)">Kim</tspan></text>'
        '<text x="44" y="186" font-size="20" fill="%s">%s</text>'
        '<text class="m" x="44" y="238" font-size="16" fill="%s">$</text>'
        % (CORAL, esc(CFG["eyebrow"]), CREAM, SOFT, esc(CFG["headline"]), MUTE)
        + typed
        + '<circle cx="48" cy="271" r="4" fill="%s"><animate attributeName="opacity" values="1;.25;1" dur="2.4s" repeatCount="indefinite"/></circle>'
        '<text class="m" x="62" y="275" font-size="11.5" fill="%s">%s</text>' % (VOLT, MUTE, esc(CFG["availability"]))
    )
    body = (
        '<g clip-path="url(#round)"><rect width="%d" height="%d" fill="url(#bg)"/>%s'
        '<rect width="%d" height="%d" fill="url(#dots)" mask="url(#dm)"/>%s%s%s</g>'
        '<rect x="0.5" y="0.5" width="%d" height="%d" rx="22" stroke="%s" stroke-opacity=".12"/>'
        % (W, H, blobs, W, H, orbits, core, left, W - 1, H - 1, CREAM)
    )
    write(
        "header.svg",
        svg(W, H, body, "Dongwook Kim, AI Engineer and full-stack developer", CFG["headline"], defs),
    )


# ---------------------------------------------------------------- small pieces


def build_links():
    for i, l in enumerate(CFG["links"]):
        n = len(l["label"])
        tw = round(n * 7.8, 1)
        w = int(tw + 54)
        body = (
            '<rect x="0.5" y="0.5" width="%d" height="35" rx="18" fill="%s" stroke="%s" stroke-opacity=".55"/>'
            '<circle cx="20" cy="18" r="4" fill="%s"/>'
            '<text class="m" x="33" y="23" font-size="13" font-weight="700" fill="%s" textLength="%s" lengthAdjust="spacing">%s</text>'
            % (w - 1, RAISED, l["color"], l["color"], CREAM, tw, esc(l["label"]))
        )
        write("link-%d.svg" % i, svg(w, 36, body, l["label"]))


def build_section(slug, num, title, tag=""):
    # Own dark background so the title stays readable on GitHub's light and dark themes.
    W, H = 900, 56
    body = (
        '<rect x="0.5" y="0.5" width="%d" height="%d" rx="16" fill="%s" stroke="%s" stroke-opacity=".09"/>'
        '<rect x="0" y="%d" width="%d" height="2" fill="url(#ln)" clip-path="url(#cut)"/>'
        '<text class="m" x="24" y="34" font-size="13" font-weight="700" fill="%s" letter-spacing="1">%s</text>'
        '<text x="58" y="36" font-size="22" font-weight="800" fill="%s" letter-spacing="-.3">%s</text>'
        % (W - 1, H - 1, PANEL, CREAM, H - 2, W, CORAL, num, CREAM, esc(title))
    )
    if tag:
        body += '<text class="m" x="%d" y="33" font-size="11" fill="%s" text-anchor="end">%s</text>' % (W - 24, MUTE, esc(tag))
    defs = (
        '<linearGradient id="ln" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="%s"/>'
        '<stop offset=".5" stop-color="%s" stop-opacity=".3"/><stop offset="1" stop-color="%s" stop-opacity="0"/></linearGradient>'
        '<clipPath id="cut"><rect width="%d" height="%d" rx="16"/></clipPath>' % (CORAL, CORAL, CORAL, W, H)
    )
    write("sec-%s.svg" % slug, svg(W, H, body, title, "", defs))


# ---------------------------------------------------------------- stats


def build_stats(d):
    W, H = 900, 150
    tiles = [
        ("CONTRIBUTIONS", "{:,}".format(d["total"]), "last 12 months", CORAL),
        ("LAST 30 DAYS", "{:,}".format(d["last30"]), "contributions", AQUA),
        ("PULL REQUESTS", str(d["prs"]), "last 12 months", IRIS),
        ("LONGEST STREAK", str(d["longest"]), "days in a row", VOLT),
        ("PUBLIC REPOS", str(d["public_repos"]), "%d originals" % d["originals"], BLUSH),
    ]
    tw, gap = 164, 20
    out, style = [], ".t{animation:rise .9s cubic-bezier(.2,.8,.2,1) both}@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}"
    defs = ""
    for i, (label, value, sub, col) in enumerate(tiles):
        x = i * (tw + gap)
        defs += (
            '<linearGradient id="g%d" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="%s"/>'
            '<stop offset="1" stop-color="%s" stop-opacity="0"/></linearGradient>' % (i, col, col)
        )
        size = 46 if len(value) <= 4 else 38
        out.append(
            '<g class="t" style="animation-delay:%dms">'
            '<rect x="%d.5" y="0.5" width="%d" height="%d" rx="18" fill="%s" stroke="%s" stroke-opacity=".09"/>'
            '<rect x="%d" y="0" width="%d" height="3" rx="1.5" fill="url(#g%d)"/>'
            '<text class="m" x="%d" y="38" font-size="10.5" font-weight="600" fill="%s" letter-spacing="1.4">%s</text>'
            '<text x="%d" y="94" font-size="%d" font-weight="800" fill="%s" letter-spacing="-1.5">%s</text>'
            '<text class="m" x="%d" y="124" font-size="10.5" fill="%s">%s</text></g>'
            % (i * 110, x, tw - 1, H - 1, PANEL, CREAM, x + 18, tw - 36, i, x + 18, col, label, x + 18, size, CREAM, value, x + 18, MUTE, esc(sub))
        )
    write("stats.svg", svg(W, H, "".join(out), "GitHub activity summary", "Contributions, pull requests, streak, active days and repositories", defs, style))


def build_activity(d):
    W, H = 900, 214
    cell, gap, x0, y0 = 12, 3, 46, 70
    weeks = d["weeks"]
    nz = sorted(c["contributionCount"] for w in weeks for c in w["contributionDays"] if c["contributionCount"])
    q = [nz[int(len(nz) * p)] for p in (0.25, 0.5, 0.75)] if nz else [1, 2, 3]
    ramp = ["#1d201a", "#5b2a1d", "#a8431f", CORAL, "#ffb08a"]

    def level(n):
        if n == 0:
            return 0
        return 1 + sum(n > t for t in q)

    cells, months, last_m = [], [], None
    for wi, w in enumerate(weeks):
        for c in w["contributionDays"]:
            n = c["contributionCount"]
            x, y = x0 + wi * (cell + gap), y0 + c["weekday"] * (cell + gap)
            cells.append(
                '<rect class="c" style="animation-delay:%dms" x="%d" y="%d" width="%d" height="%d" rx="3" fill="%s"><title>%s: %d</title></rect>'
                % (wi * 14, x, y, cell, cell, ramp[level(n)], c["date"], n)
            )
        m = dt.date.fromisoformat(w["contributionDays"][0]["date"]).strftime("%b")
        if m != last_m and (wi == 0 or wi * (cell + gap) + x0 < W - 50):
            months.append('<text class="m" x="%d" y="%d" font-size="10" fill="%s">%s</text>' % (x0 + wi * (cell + gap), y0 - 10, MUTE, m))
            last_m = m
    days = "".join(
        '<text class="m" x="14" y="%d" font-size="9.5" fill="%s">%s</text>' % (y0 + i * (cell + gap) + 10, MUTE, n)
        for i, n in ((1, "Mon"), (3, "Wed"), (5, "Fri"))
    )
    legend_x = W - 24 - 5 * (cell + 3) - 62
    legend = (
        '<text class="m" x="%d" y="%d" font-size="10" fill="%s" text-anchor="end">Less</text>' % (legend_x - 6, H - 20, MUTE)
        + "".join('<rect x="%d" y="%d" width="%d" height="%d" rx="3" fill="%s"/>' % (legend_x + i * (cell + 3), H - 30, cell, cell, c) for i, c in enumerate(ramp))
        + '<text class="m" x="%d" y="%d" font-size="10" fill="%s">More</text>' % (legend_x + 5 * (cell + 3) + 6, H - 20, MUTE)
    )
    head = (
        '<text x="24" y="38" font-size="17" font-weight="700" fill="%s">Contribution graph</text>'
        '<text class="m" x="%d" y="38" font-size="11.5" fill="%s" text-anchor="end"><tspan fill="%s" font-weight="700">%s</tspan> contributions in the last year</text>'
        % (CREAM, W - 24, MUTE, CORAL, "{:,}".format(d["total"]))
    )
    foot = '<text class="m" x="24" y="%d" font-size="10.5" fill="%s">longest streak %d days  /  %d active days</text>' % (H - 20, MUTE, d["longest"], d["active_days"])
    style = ".c{animation:pop .5s ease-out both}@keyframes pop{from{opacity:0;transform:scale(.4)}to{opacity:1;transform:scale(1)}}.c{transform-box:fill-box;transform-origin:center}"
    write("activity.svg", svg(W, H, panel(W, H) + head + "".join(months) + days + "".join(cells) + foot + legend, "Contribution graph for the last year", "%d contributions" % d["total"], "", style))


def build_languages(d):
    W, H = 900, 214
    tot = sum(d["lang_totals"].values()) or 1
    ranked = sorted(d["lang_totals"].items(), key=lambda kv: -kv[1])
    top, rest = ranked[:7], ranked[7:]
    items = [(n, v / tot * 100) for n, v in top]
    if rest:
        items.append(("Other", sum(v for _, v in rest) / tot * 100))
    palette = [CORAL, AQUA, IRIS, VOLT, BLUSH, "#6ea8ff", "#ffb86b", MUTE]
    bar_x, bar_w, bar_y = 24, W - 48, 66
    segs, x = [], bar_x
    for i, (n, p) in enumerate(items):
        w = bar_w * p / 100
        segs.append('<rect x="%.2f" y="%d" width="%.2f" height="16" fill="%s"/>' % (x, bar_y, max(w - 2, 1), palette[i]))
        x += w
    legend = []
    for i, (n, p) in enumerate(items):
        col, row = i % 4, i // 4
        lx, ly = 24 + col * 214, 128 + row * 36
        legend.append(
            '<circle cx="%d" cy="%d" r="5" fill="%s"/><text x="%d" y="%d" font-size="14" font-weight="600" fill="%s">%s</text>'
            '<text class="m" x="%d" y="%d" font-size="11.5" fill="%s">%.1f%%</text>'
            % (lx + 5, ly - 4, palette[i], lx + 18, ly, CREAM, esc(n), lx + 18, ly + 16, MUTE, p)
        )
    defs = '<clipPath id="bar"><rect x="%d" y="%d" width="%d" height="16" rx="8"/></clipPath>' % (bar_x, bar_y, bar_w)
    head = (
        '<text x="24" y="38" font-size="17" font-weight="700" fill="%s">Languages</text>'
        '<text class="m" x="%d" y="38" font-size="11.5" fill="%s" text-anchor="end">by code volume, public repos</text>' % (CREAM, W - 24, MUTE)
    )
    bar = '<g clip-path="url(#bar)"><g class="grow">%s</g></g>' % "".join(segs)
    style = ".grow{transform-box:fill-box;transform-origin:left center;animation:grow 1.2s cubic-bezier(.2,.8,.2,1) both}@keyframes grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}"
    write("languages.svg", svg(W, H, panel(W, H) + head + bar + "".join(legend), "Language breakdown", ", ".join("%s %.0f%%" % (n, p) for n, p in items), defs, style))


# ---------------------------------------------------------------- projects


def build_cards(d):
    W, H = 440, 176
    out = []
    for cfg in CFG["featured"]:
        r = d["by_name"].get(cfg["repo"])
        if not r:
            print("warning: featured repo not found or not public:", cfg["repo"], file=sys.stderr)
            continue
        acc = cfg["accent"]
        lang = r["primaryLanguage"] or {"name": "", "color": MUTE}
        lines = wrap(cfg["blurb"], 56, 2)
        desc = "".join('<text x="24" y="%d" font-size="13.5" fill="%s">%s</text>' % (80 + i * 20, SOFT, esc(l)) for i, l in enumerate(lines))
        tags, x = [], 24
        for t in cfg["tags"]:
            tw = round(len(t) * 6.3, 1)
            w = tw + 20
            if x + w > W - 24:
                break
            tags.append(
                '<rect x="%.1f" y="118" width="%.1f" height="22" rx="11" fill="%s" fill-opacity=".05" stroke="%s" stroke-opacity=".14"/>'
                '<text class="m" x="%.1f" y="133" font-size="10.5" fill="%s" textLength="%s" lengthAdjust="spacing">%s</text>'
                % (x, w, CREAM, CREAM, x + 10, SOFT, tw, esc(t))
            )
            x += w + 8
        fx = 24
        foot = '<circle cx="%d" cy="162" r="5" fill="%s"/><text class="m" x="%d" y="166" font-size="11" fill="%s">%s</text>' % (fx + 5, lang["color"] or MUTE, fx + 16, MUTE, esc(lang["name"]))
        fx += 16 + len(lang["name"]) * 6.6 + 18
        if r["stargazerCount"]:
            foot += '<text class="m" x="%d" y="166" font-size="11" fill="%s">\u2605 %d</text>' % (fx, MUTE, r["stargazerCount"])
            fx += 48
        if cfg.get("live"):
            foot += (
                '<circle cx="%d" cy="162" r="3.5" fill="%s"><animate attributeName="opacity" values="1;.2;1" dur="2.4s" repeatCount="indefinite"/></circle>'
                '<text class="m" x="%d" y="166" font-size="11" fill="%s">live</text>' % (fx + 3, AQUA, fx + 13, AQUA)
            )
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(r["pushedAt"].replace("Z", "+00:00"))).days
        if age <= 90:
            foot += '<text class="m" x="%d" y="166" font-size="11" fill="%s" text-anchor="end">updated %s</text>' % (W - 24, MUTE, short_date(r["pushedAt"]))
        defs = (
            '<linearGradient id="a" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s" stop-opacity="0"/></linearGradient>'
            '<radialGradient id="glow" cx="1" cy="0" r="1"><stop offset="0" stop-color="%s" stop-opacity=".16"/><stop offset="1" stop-color="%s" stop-opacity="0"/></radialGradient>'
            '<clipPath id="r"><rect width="%d" height="%d" rx="18"/></clipPath>' % (acc, acc, acc, acc, W, H)
        )
        body = (
            '<g clip-path="url(#r)"><rect width="%d" height="%d" fill="%s"/><rect width="%d" height="%d" fill="url(#glow)"/>'
            '<rect x="0" y="0" width="%d" height="3" fill="url(#a)"/></g>'
            '<rect x="0.5" y="0.5" width="%d" height="%d" rx="18" stroke="%s" stroke-opacity=".09"/>'
            '<text class="m" x="24" y="34" font-size="11" fill="%s">dwk601 /</text>'
            '<text x="24" y="58" font-size="19" font-weight="800" fill="%s" letter-spacing="-.3">%s</text>'
            '<text x="%d" y="40" font-size="16" fill="%s" text-anchor="end">\u2197</text>'
            % (W, H, PANEL, W, H, W, W - 1, H - 1, CREAM, MUTE, CREAM, esc(cfg["title"]), W - 24, acc)
            + desc
            + "".join(tags)
            + foot
        )
        write("card-%s.svg" % cfg["repo"], svg(W, H, body, cfg["title"], cfg["blurb"], defs))
        out.append((cfg, r))
    return out


# ---------------------------------------------------------------- stack


def build_stack():
    W = 900
    label_w, x_start, x_max, row_h = 150, 164, W - 24, 36
    y, rows, h_total = 28, [], 0
    for g in CFG["stack"]:
        x, line_y = x_start, y
        rows.append('<text class="m" x="24" y="%d" font-size="11" font-weight="700" fill="%s" letter-spacing="1.2">%s</text>' % (y + 16, g["color"], esc(g["group"].upper())))
        for it in g["items"]:
            tw = round(len(it) * 6.6, 1)
            w = tw + 34
            if x + w > x_max:
                x, line_y = x_start, line_y + row_h
            rows.append(
                '<rect x="%.1f" y="%d" width="%.1f" height="26" rx="13" fill="%s" fill-opacity=".045" stroke="%s" stroke-opacity=".12"/>'
                '<circle cx="%.1f" cy="%d" r="3" fill="%s"/>'
                '<text class="m" x="%.1f" y="%d" font-size="11" fill="%s" textLength="%s" lengthAdjust="spacing">%s</text>'
                % (x, line_y, w, CREAM, CREAM, x + 13, line_y + 13, g["color"], x + 23, line_y + 17, CREAM, tw, esc(it))
            )
            x += w + 7
        y = line_y + row_h + 10
        h_total = y
    H = int(h_total + 8)
    write("stack.svg", svg(W, H, panel(W, H) + "".join(rows), "Toolbox", "; ".join("%s: %s" % (g["group"], ", ".join(g["items"])) for g in CFG["stack"])))


# ---------------------------------------------------------------- footer


def build_footer():
    W, H = 900, 150

    def wave(amp, off, dur, col, op, rev=False):
        d_path, x, up = "M0,%d" % off, 0, True
        while x < 2 * W:
            d_path += " q150,%d 300,0" % (-amp * 2 if up else amp * 2)
            up, x = not up, x + 300
        d_path += " V%d H0 Z" % H
        a, b = (-W, 0) if rev else (0, -W)
        return (
            '<path d="%s" fill="%s" fill-opacity="%s"><animateTransform attributeName="transform" '
            'type="translate" from="%d 0" to="%d 0" dur="%ss" repeatCount="indefinite"/></path>'
            % (d_path, col, op, a, b, dur)
        )

    body = (
        '<g clip-path="url(#fr)"><rect width="%d" height="%d" fill="%s"/>' % (W, H, PANEL)
        + wave(9, 96, 18, IRIS, ".20")
        + wave(10, 108, 13, AQUA, ".16", True)
        + wave(8, 120, 9, CORAL, ".30")
        + '</g><rect x="0.5" y="0.5" width="%d" height="%d" rx="22" stroke="%s" stroke-opacity=".09"/>' % (W - 1, H - 1, CREAM)
        + '<text x="450" y="46" font-size="15" fill="%s" text-anchor="middle" font-weight="600">Thanks for stopping by.</text>'
        '<text class="m" x="450" y="67" font-size="11" fill="%s" text-anchor="middle">built with a stdlib Python script and GitHub Actions, refreshed daily</text>' % (SOFT, MUTE)
    )
    defs = '<clipPath id="fr"><rect width="%d" height="%d" rx="22"/></clipPath>' % (W, H)
    write("footer.svg", svg(W, H, body, "Footer", "", defs))


# ---------------------------------------------------------------- readme


def render_readme(d, cards):
    tpl = (ROOT / "scripts" / "README.tpl.md").read_text(encoding="utf-8")
    link_html = " &nbsp;".join(
        '<a href="%s"><img src="assets/link-%d.svg" alt="%s" height="36"></a>' % (l["url"], i, esc(l["label"]))
        for i, l in enumerate(CFG["links"])
    )
    cards_html = []
    for cfg, r in cards:
        cards_html.append(
            '<a href="%s"><img src="assets/card-%s.svg" alt="%s: %s" width="49%%"></a>'
            % (r["url"], cfg["repo"], esc(cfg["title"]), esc(cfg["blurb"]))
        )
    pairs = ["&nbsp;".join(cards_html[i : i + 2]) for i in range(0, len(cards_html), 2)]
    live = " &nbsp;/&nbsp; ".join(
        '<a href="%s">%s</a>' % (c["live"], re.sub(r"^https?://|/en$|/$", "", c["live"])) for c, _ in cards if c.get("live")
    )
    hide = set(CFG["recent"]["hide"])
    recent = []
    for r in d["repos"]:
        if r["name"] in hide:
            continue
        nodes = ((r.get("defaultBranchRef") or {}).get("target") or {}).get("history", {}).get("nodes", [])
        msg = next((n["messageHeadline"] for n in nodes if not n["messageHeadline"].startswith("Merge ")), "")
        msg = re.sub(r"\s+", " ", msg).strip()
        msg = (msg[:72] + "\u2026") if len(msg) > 73 else msg
        line = "- **[%s](%s)**" % (r["name"], r["url"])
        if msg:
            line += " &middot; %s" % esc(msg)
        line += " &middot; <sub>%s</sub>" % ago(r["pushedAt"])
        recent.append(line)
        if len(recent) >= CFG["recent"]["count"]:
            break
    out = (
        tpl.replace("{{LINKS}}", link_html)
        .replace("{{CARDS}}", "\n".join('<p align="center">%s</p>' % p for p in pairs))
        .replace("{{LIVE}}", live)
        .replace("{{RECENT}}", "\n".join(recent))
        .replace("{{UPDATED}}", dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"))
    )
    (ROOT / "README.md").write_text(out, encoding="utf-8")


def main():
    d = derive(fetch())
    ASSETS.mkdir(exist_ok=True)
    for old in ASSETS.glob("*.svg"):  # drop assets of removed projects or links
        old.unlink()
    build_header()
    build_links()
    for i, (slug, num, title, tag) in enumerate(
        [
            ("about", "01", "About", ""),
            ("activity", "02", "Activity", "live from the GitHub API"),
            ("projects", "03", "Selected work", ""),
            ("recent", "04", "Recently shipped", ""),
            ("stack", "05", "Toolbox", ""),
        ]
    ):
        build_section(slug, num, title, tag)
    build_stats(d)
    build_activity(d)
    build_languages(d)
    cards = build_cards(d)
    build_stack()
    build_footer()
    render_readme(d, cards)
    print("ok: %d contributions, streak %d, %d featured cards" % (d["total"], d["streak"], len(cards)))


if __name__ == "__main__":
    main()
