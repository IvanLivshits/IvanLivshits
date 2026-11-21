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
THEMES = {
    "dark_mode.svg": dict(bg="#161b22", fg="#c9d1d9", key="#ffa657", val="#a5d6ff",
                          dim="#616e7f", add="#3fb950", rem="#f85149"),
}


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
    return [("fg", left + "—" * (width - len(left) - 4) + "-—-")]


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


def render(theme, art, lines):
    art_w = max(len(l) for l in art)
    art_h, info_h = len(art) * ART_LH, len(lines) * LH
    inner = max(art_h, info_h)
    info_x = PAD + art_w * ART_CW + 3 * CW
    width = round(info_x + COLS * CW + PAD)
    height = round(inner + PAD * 2)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,'
        f'\'Liberation Mono\',\'DejaVu Sans Mono\',monospace" font-size="{FONT}px">',
        f'<rect width="{width}" height="{height}" rx="12" fill="{theme["bg"]}"/>',
    ]

    def text(x, y, spans, cw, size=None):
        n = sum(len(t) for _, t in spans)
        if not n:
            return
        body = "".join(f'<tspan fill="{theme[c]}">{escape(t).replace(" ", NBSP)}</tspan>' for c, t in spans)
        fs = f' font-size="{size}px"' if size else ""
        # textLength pins the width, so columns line up whatever font the viewer has
        out.append(f'<text x="{x:.1f}" y="{y:.1f}"{fs} textLength="{n * cw:.1f}" lengthAdjust="spacing">{body}</text>')

    top = PAD + (inner - art_h) / 2
    for i, l in enumerate(art):
        lead = len(l) - len(l.lstrip())
        text(PAD + lead * ART_CW, top + i * ART_LH + ART_FONT * 0.9, [("fg", l.strip())], ART_CW, ART_FONT)
    top = PAD + (inner - info_h) / 2
    for i, spans in enumerate(lines):
        text(info_x, top + i * LH + 15, spans, CW)
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main():
    with open(os.path.join(HERE, "ascii.txt")) as f:
        art = [l.rstrip("\n") for l in f if l.strip() or True]
    while art and not art[-1].strip():
        art.pop()
    lines = info_lines(load_stats())
    for name, theme in THEMES.items():
        with open(os.path.join(HERE, name), "w") as f:
            f.write(render(theme, art, lines))
        print("wrote", name)


if __name__ == "__main__":
    main()
