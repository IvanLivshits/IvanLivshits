#!/usr/bin/env python3
"""Build dark_mode.svg: ASCII portrait + neofetch-style card.

Stdlib only. Stats come from the GitHub GraphQL API using ACCESS_TOKEN
(a personal token: also counts private repos) or, failing that, GITHUB_TOKEN
(public data only). Without any token the previous numbers in stats.json are kept.
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from xml.sax.saxutils import escape

# ----------------------------------------------------------------- config --
LOGIN = "IvanLivshits"
TITLE = "ivan@livshits"
CAREER_START = dt.date(2021, 2, 1)  # "Uptime" = time in software engineering

INFO = [  # (key, value) rows; None = blank line; a bare string = section header
    ("OS", "Ubuntu Linux"),
    ("Uptime", "{uptime}"),
    ("Kernel", "Senior Software Engineer, Backend"),
    None,
    ("Languages.Programming", "TypeScript, Python, Java, Go, Rust"),
    ("Languages.Real", "Russian, English"),
    None,
    ("Stack.Backend", "Node.js, NestJS, PostgreSQL, Kafka, gRPC"),
    ("Stack.Infra", "AWS, Kubernetes, Argo CD, Grafana"),
    ("Stack.AI", "LLM pipelines, LLMOps, AI security"),
    None,
    ("Hobbies", "Volleyball (ex-pro)"),
    ("Background", "Aerospace engineer, space launches"),
    None,
    "Contact",
    ("Telegram", "@Ivan_Livshits"),
    ("LinkedIn", "ivan-livshits-a94204220"),
    None,
    "GitHub Stats",
]
# ---------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
COLS = 62          # width of the info column, in characters
FONT, CW, LH = 16, 9.6, 20   # font size, char advance, line height (px)
ART_FONT, ART_CW, ART_LH = 8.8, 5.28, 11  # the portrait uses a much smaller cell: it is a picture, not text
PAD = 22
NBSP = "\u00a0"  # plain spaces collapse inside SVG text

# One dark card for every viewer: the portrait is drawn bright-on-dark.
# Palette: black, signal yellow, cyan, red.
THEME = dict(bg="#05070a", edge="#fcee0a", art="#35e0f0", fg="#c8d3da", hdr="#ff2a4f",
             key="#fcee0a", val="#00f0ff", dim="#2f4651", add="#00ff9f", rem="#ff2a4f")
BOOT = ("whoami --verbose", "root")   # command typed out when the card loads, and its result


# ------------------------------------------------------------------ stats --
def gql(query, variables, token):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {token}", "User-Agent": "profile-card"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.load(r)
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"]


def fetch_stats(token):
    user = gql("""query($login:String!){ user(login:$login){
        id createdAt followers{totalCount} } }""", {"login": LOGIN}, token)["user"]

    # repositories: owned, and everything the user has access to / contributed to
    repos, stars, owned, cursor = [], 0, 0, None
    while True:
        page = gql("""query($login:String!,$cursor:String){ user(login:$login){
            repositories(first:100, after:$cursor,
                ownerAffiliations:[OWNER,COLLABORATOR,ORGANIZATION_MEMBER]){
              pageInfo{hasNextPage endCursor}
              nodes{ nameWithOwner isFork owner{login} stargazerCount
                     defaultBranchRef{name} } } } }""",
                   {"login": LOGIN, "cursor": cursor}, token)["user"]["repositories"]
        for n in page["nodes"]:
            repos.append(n)
            if n["owner"]["login"].lower() == LOGIN.lower():
                owned += 1
                stars += n["stargazerCount"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    # commits and lines of code: walk the default-branch history of every repo
    commits = added = removed = 0
    for n in repos:
        if not n["defaultBranchRef"] or n["isFork"]:
            continue
        owner, name = n["nameWithOwner"].split("/")
        cursor = None
        while True:
            try:
                hist = gql("""query($o:String!,$n:String!,$id:ID!,$cursor:String){
                    repository(owner:$o,name:$n){ defaultBranchRef{ target{ ... on Commit{
                      history(first:100, after:$cursor, author:{id:$id}){
                        totalCount pageInfo{hasNextPage endCursor}
                        nodes{additions deletions} } } } } } }""",
                           {"o": owner, "n": name, "id": user["id"], "cursor": cursor}, token)
            except Exception as e:  # one unreadable repo must not kill the run
                print(f"skip {n['nameWithOwner']}: {e}", file=sys.stderr)
                break
            hist = hist["repository"]["defaultBranchRef"]["target"]["history"]
            if cursor is None:
                commits += hist["totalCount"]
            for c in hist["nodes"]:
                added += c["additions"]
                removed += c["deletions"]
            if not hist["pageInfo"]["hasNextPage"]:
                break
            cursor = hist["pageInfo"]["endCursor"]

    # the contribution calendar also knows commits the history walk can't see
    # (repos this token can't read); take whichever count is larger
    calendar = 0
    for year in range(int(user["createdAt"][:4]), dt.date.today().year + 1):
        try:
            c = gql("""query($login:String!,$from:DateTime!,$to:DateTime!){ user(login:$login){
                contributionsCollection(from:$from,to:$to){ totalCommitContributions } } }""",
                    {"login": LOGIN, "from": f"{year}-01-01T00:00:00Z",
                     "to": f"{year}-12-31T23:59:59Z"}, token)
            calendar += c["user"]["contributionsCollection"]["totalCommitContributions"]
        except Exception as e:
            print(f"skip calendar {year}: {e}", file=sys.stderr)
    commits = max(commits, calendar)

    return dict(repos=owned, contributed=len(repos) - owned, stars=stars, commits=commits,
                followers=user["followers"]["totalCount"], added=added, removed=removed)


def load_stats():
    cache = os.path.join(HERE, "stats.json")
    token = os.environ.get("ACCESS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        stats = fetch_stats(token)
        with open(cache, "w") as f:
            json.dump(stats, f, indent=2)
            f.write("\n")
        return stats
    if os.path.exists(cache):
        print("no token: reusing stats.json", file=sys.stderr)
        with open(cache) as f:
            return json.load(f)
    sys.exit("no ACCESS_TOKEN/GITHUB_TOKEN and no stats.json yet")


# ----------------------------------------------------------------- layout --
def uptime(today):
    y, m, d = (today.year - CAREER_START.year, today.month - CAREER_START.month,
               today.day - CAREER_START.day)
    if d < 0:
        m -= 1
        prev = today.replace(day=1) - dt.timedelta(days=1)
        d += prev.day
    if m < 0:
        y, m = y - 1, m + 12
    plural = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"
    return f"{plural(y, 'year')}, {plural(m, 'month')}, {plural(d, 'day')}"


def kv(key, value, width=COLS):
    """'. Key: ........ value' as coloured spans, exactly `width` chars."""
    dots = width - len(key) - len(value) - 5
    return [("dim", ". "), ("key", key), ("fg", ":"), ("dim", " " + "." * max(dots, 1) + " "),
            ("val", value)]


def header(title, width=COLS):
    left = f"- {title} " if title != TITLE else f"{title} "
    return [("hdr", left + "—" * (width - len(left) - 4) + "-—-")]


def info_lines(s):
    lines = [header(TITLE)]
    for row in INFO:
        if row is None:
            lines.append([("dim", ".")])
        elif isinstance(row, str):
            lines.append(header(row))
        else:
            lines.append(kv(row[0], row[1].format(uptime=uptime(dt.date.today()))))
    half = COLS // 2 - 1
    for (k1, v1), (k2, v2) in (
        ((f"Repos", f"{s['repos']} {{Contributed: {s['contributed']}}}"), ("Stars", f"{s['stars']:,}")),
        (("Commits", f"{s['commits']:,}"), ("Followers", f"{s['followers']:,}")),
    ):
        lines.append(kv(k1, v1, half + 2) + [("fg", " | ")] + kv(k2, v2, COLS - half - 3)[1:])
    loc, plus, minus = f"{s['added'] - s['removed']:,}", f"{s['added']:,}++", f"{s['removed']:,}--"
    key = "Lines of Code on GitHub"
    dots = COLS - len(key) - len(loc) - len(plus) - len(minus) - 12
    lines.append([("dim", ". "), ("key", key), ("fg", ":"), ("dim", " " + "." * max(dots, 1) + " "),
                  ("val", loc), ("fg", " ( "), ("add", plus), ("fg", ", "), ("rem", minus), ("fg", " )")])
    return lines


def render(art, lines):
    t = THEME
    bar, cut = 30, 20                       # header strip height, size of the cut corners
    art_w = max(len(l) for l in art)
    lines = [None, []] + lines               # room for the boot line on top
    art_h, info_h = len(art) * ART_LH, len(lines) * LH
    inner = max(art_h, info_h)
    info_x = PAD + art_w * ART_CW + 3 * CW
    W = round(info_x + COLS * CW + PAD)
    H = round(bar + inner + PAD * 2)
    shape = f"{cut},1 {W - 1},1 {W - 1},{H - cut} {W - cut},{H - 1} 1,{H - 1} 1,{cut}"
    art_top = bar + PAD + (inner - art_h) / 2
    info_top = bar + PAD + (inner - info_h) / 2

    def line(x, y, spans, cw, size=None):
        """One row of text; textLength pins the width whatever font the viewer has."""
        n = sum(len(sp[1]) for sp in spans)
        if not n:
            return ""
        body = "".join(
            f'<tspan{" fill=" + chr(34) + t[sp[0]] + chr(34) if sp[0] else ""}{sp[2] if len(sp) > 2 else ""}>'
            f'{escape(sp[1]).replace(" ", NBSP)}</tspan>' for sp in spans)
        fs = f' font-size="{size}px"' if size else ""
        return f'<text x="{x:.1f}" y="{y:.1f}"{fs} textLength="{n * cw:.1f}" lengthAdjust="spacing">{body}</text>'

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,'
        f'\'Liberation Mono\',\'DejaVu Sans Mono\',monospace" font-size="{FONT}px">',
        "<style>",
        "@keyframes jolt{0%,90%,100%{transform:translate(0,0)}91%{transform:translate(-3px,0)}"
        "93%{transform:translate(2px,1px)}95%{transform:translate(-1px,0)}}",
        "@keyframes ghost{0%,90%,97%,100%{opacity:0;transform:translate(0,0)}91%{opacity:.75;transform:translate(6px,-1px)}"
        "93%{opacity:.75;transform:translate(-5px,1px)}95%{opacity:.5;transform:translate(3px,0)}}",
        "@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}}",
        "@keyframes sweep{from{transform:translateY(-90px)}to{transform:translateY(%dpx)}}" % H,
        ".main{animation:jolt 7s infinite}.g1{animation:ghost 7s infinite}"
        ".g2{animation:ghost 7s infinite reverse}",
        ".cur{animation:blink 1s infinite}.dot{animation:blink 2s infinite}"
        ".sweep{animation:sweep 6s linear infinite}",
        "@media (prefers-reduced-motion:reduce){*{animation:none!important}}",
        "</style>",
        "<defs>",
        f'<clipPath id="card"><polygon points="{shape}"/></clipPath>',
        '<pattern id="scan" width="3" height="3" patternUnits="userSpaceOnUse">'
        '<rect width="3" height="1" fill="#000" opacity=".4"/></pattern>',
        f'<linearGradient id="beam" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{t["val"]}" stop-opacity="0"/>'
        f'<stop offset=".5" stop-color="{t["val"]}" stop-opacity=".07"/>'
        f'<stop offset="1" stop-color="{t["val"]}" stop-opacity="0"/></linearGradient>',
        "</defs>",
        f'<polygon points="{shape}" fill="{t["bg"]}" stroke="{t["edge"]}" stroke-width="1.5"/>',
        # header strip
        f'<polygon points="{cut},1 {W - 1},1 {W - 1},{bar} 1,{bar} 1,{cut}" fill="{t["edge"]}" opacity=".1"/>',
        f'<line x1="1" y1="{bar}" x2="{W - 1}" y2="{bar}" stroke="{t["edge"]}" stroke-opacity=".6"/>',
        f'<text x="{cut + 10}" y="20" font-size="12px" font-weight="bold" letter-spacing="2" fill="{t["edge"]}">'
        f'{TITLE} // profile</text>',
        f'<text x="{W - 34}" y="20" font-size="12px" letter-spacing="2" text-anchor="end" fill="{t["add"]}">ONLINE</text>',
        f'<circle class="dot" cx="{W - 20}" cy="16" r="4" fill="{t["add"]}"/>',
    ]

    # portrait, with two colour ghosts that flash sideways during the glitch
    rows = []
    for i, l in enumerate(art):
        lead = len(l) - len(l.lstrip())
        rows.append(line(PAD + lead * ART_CW, art_top + i * ART_LH + ART_FONT * 0.9, [("", l.strip())], ART_CW, ART_FONT))
    out.append(f'<g clip-path="url(#card)">')
    out.append(f'<g class="g1" fill="{t["rem"]}" opacity="0"><use xlink:href="#art" href="#art"/></g>')
    out.append(f'<g class="g2" fill="{t["edge"]}" opacity="0"><use xlink:href="#art" href="#art"/></g>')
    out.append(f'<g class="main" fill="{t["art"]}"><g id="art">' + "".join(rows) + "</g></g>")
    out.append("</g>")

    # info column
    for i, spans in enumerate(lines):
        y = info_top + i * LH + 15
        if i == 0:  # boot line: typed out once, then a blinking cursor
            typed = [("add", "> "), ("fg", BOOT[0]), ("dim", " ... "), ("add", BOOT[1])]
            n = sum(len(sp[1]) for sp in typed)
            out.append(f'<clipPath id="type"><rect x="{info_x:.1f}" y="{y - 16:.1f}" height="{LH}" width="{n * CW:.1f}">'
                       f'<animate attributeName="width" from="0" to="{n * CW:.1f}" dur="2.6s" begin="0.4s" fill="freeze"/>'
                       f'</rect></clipPath>')
            out.append(f'<g clip-path="url(#type)">{line(info_x, y, typed, CW)}</g>')
            out.append(f'<rect class="cur" x="{info_x + (n + 1) * CW:.1f}" y="{y - 13:.1f}" width="{CW:.1f}" height="16" fill="{t["add"]}"/>')
        elif spans:
            out.append(line(info_x, y, spans, CW))

    # scanlines and a slow light sweep over everything
    out.append(f'<g clip-path="url(#card)" pointer-events="none"><rect width="{W}" height="{H}" fill="url(#scan)"/>'
               f'<rect class="sweep" width="{W}" height="90" fill="url(#beam)"/></g>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main():
    with open(os.path.join(HERE, "ascii.txt")) as f:
        art = [l.rstrip("\n") for l in f]
    while art and not art[-1].strip():
        art.pop()
    with open(os.path.join(HERE, "dark_mode.svg"), "w") as f:
        f.write(render(art, info_lines(load_stats())))
    print("wrote dark_mode.svg")


if __name__ == "__main__":
    main()
