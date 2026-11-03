#!/usr/bin/env python3
"""Build the whyfull website (GitHub Pages) into site/_site.

    pip install markdown
    python3 site/build.py
    python3 -m http.server -d site/_site 8000   # then open http://localhost:8000/whyfull/ ... see BASE

Guides are Markdown files in site/guides/ with a small front matter block
(title, description, short). Adding a guide is adding a file.
"""

import datetime
import html
import json
import os
import re
import shutil
import sys

import markdown

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
OUT = os.path.join(HERE, "_site")
SITE = "https://amlaban65.github.io"
BASE = "/whyfull/"
REPO = "https://github.com/amlaban65/whyfull"
PYZ = REPO + "/releases/latest/download/whyfull.pyz"
TODAY = datetime.date.today().isoformat()

sys.path.insert(0, os.path.join(ROOT, "src"))
from whyfull import __version__  # noqa: E402

# What whyfull found on the demo server (tools/demo.py), in MB, for the disk bar.
FOUND = [
    ("Deleted log still open by nginx", 700, "caution"),
    ("Docker log of container api", 560, "caution"),
    ("Unused Docker images", 412, "review"),
    ("3 old kernels", 390, "review"),
    ("systemd journal over 200 MB", 360, "review"),
    ("Rotated logs in /var/log", 280, "review"),
    ("apt package cache", 240, "safe"),
    ("Docker build cache", 238, "safe"),
    ("pip cache", 220, "safe"),
    ("Old files in /tmp", 200, "review"),
    ("Crash dumps", 140, "review"),
    ("Everything else", 260, "rest"),
]

RISK_WORD = {"safe": "safe", "review": "review", "caution": "caution", "rest": "kept"}

INSTALL = (
    "curl -fsSL -o /dev/shm/whyfull \\\n  %s\n"
    "sudo python3 /dev/shm/whyfull" % PYZ
)


def read_guide(path):
    with open(path) as f:
        text = f.read()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    meta = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"')
    meta["slug"] = os.path.splitext(os.path.basename(path))[0]
    meta["body"] = text[m.end():]
    return meta


def esc(s):
    return html.escape(s, quote=True)


def page(title, description, path, body, jsonld, extra_head=""):
    url = SITE + BASE + path
    depth = path.count("/")
    up = "../" * depth
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="{ogtype}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{site}{base}og.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="{up}favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Mono:wght@400;600&family=Atkinson+Hyperlegible+Next:wght@400;600;700;800&display=swap">
<link rel="stylesheet" href="{up}style.css">
<script type="application/ld+json">{jsonld}</script>
{extra}</head>
<body>
<header class="bar">
  <a class="brand" href="{up}">whyfull</a>
  <nav aria-label="Site">
    <a href="{up}#guides">Guides</a>
    <a href="{repo}">GitHub</a>
  </nav>
</header>
<main>
{body}
</main>
<footer class="foot">
  <p>whyfull is free and open source under the MIT license. <a href="{repo}">Source on GitHub</a>.
  Found a disk filled by something these guides don't cover? <a href="{repo}/issues/new?template=new-check.yml">Tell us about it</a>.</p>
</footer>
<script src="{up}copy.js" defer></script>
</body>
</html>
""".format(title=esc(title), desc=esc(description), url=url, site=SITE, base=BASE, up=up,
           ogtype="article" if depth else "website", jsonld=json.dumps(jsonld), body=body,
           repo=REPO, extra=extra_head)


def install_block():
    return '<pre class="cmd"><code>%s</code></pre>' % esc(INSTALL)


def whyfull_aside():
    return """<aside class="tool" id="whyfull">
  <h2>Check all of this at once</h2>
  <p>whyfull looks for every cause in these guides (deleted files still held open, Docker, the journal,
  old kernels, logs, caches, inodes) and prints how much space each one uses, how risky it is to remove,
  and the command that frees it. It's a single file that runs with the Python 3 already on your server,
  and it never deletes anything itself.</p>
  %s
  <p class="small">Or install it with <code>pipx install whyfull</code>. <a href="%s">More on GitHub</a>.</p>
</aside>""" % (install_block(), REPO)


def disk_bar():
    total = sum(mb for _, mb, _ in FOUND)
    segs, legend = [], []
    for i, (name, mb, risk) in enumerate(FOUND):
        pct = 100.0 * mb / total
        segs.append('<span class="seg %s" style="--w:%.2f%%;--i:%d" title="%s: %d MB"></span>'
                    % (risk, pct, i, esc(name), mb))
        legend.append('<li><span class="sw %s"></span><span class="mb">%d MB</span> %s <em class="%s">%s</em></li>'
                      % (risk, mb, esc(name), risk, RISK_WORD[risk]))
    return """<figure class="disk">
  <p class="disk-head"><strong>/ is 100%% full</strong> <span>4.0 GB used of 4.1 GB</span></p>
  <div class="disk-bar" role="img" aria-label="Disk usage bar split by what whyfull found">%s</div>
  <figcaption>What whyfull found on a full 4 GB test server. All but 260 MB of the used space
  could be freed, and each item came with its fix.</figcaption>
  <ul class="legend">%s</ul>
</figure>""" % ("".join(segs), "".join(legend))


def guide_list(guides, skip=None):
    items = []
    for g in guides:
        if g["slug"] == skip:
            continue
        items.append('<li><a href="{href}">{title}</a><span>{short}</span></li>'.format(
            href="%sguides/%s/" % ("../../" if skip else "", g["slug"]),
            title=esc(g["title"]), short=esc(g["short"])))
    return '<ul class="guides">%s</ul>' % "".join(items)


def build_index(guides):
    body = """<section class="hero">
  <h1>Why is my Linux disk full?</h1>
  <p class="lede">whyfull finds what's filling a Linux disk and gives you the command that frees each thing,
  marked safe, review or caution. It never deletes anything itself.</p>
  %s
  <div class="run">
    <p>Run it on the full server. It's one file with no dependencies, downloaded into memory so it works even with no free space:</p>
    %s
    <p class="small">Needs Python 3.6 or newer. Also on PyPI: <code>pipx install whyfull</code>.</p>
  </div>
</section>
<section id="guides">
  <h2>Guides</h2>
  <p>Fixing it by hand? Each guide covers one common cause, with the commands to find it and free the space.</p>
  %s
</section>
<section>
  <h2>What a report looks like</h2>
  <img class="shot" src="demo.svg" width="1167" height="1518" loading="lazy"
       alt="whyfull report for a full root filesystem, listing each finding with its size, risk and fix command">
</section>""" % (disk_bar(), install_block(), guide_list(guides))
    jsonld = {
        "@context": "https://schema.org", "@type": "SoftwareApplication", "name": "whyfull",
        "description": "Finds out why a Linux disk is full and prints the command that frees each thing it finds.",
        "applicationCategory": "DeveloperApplication", "operatingSystem": "Linux",
        "softwareVersion": __version__, "url": SITE + BASE, "downloadUrl": PYZ,
        "license": "https://opensource.org/licenses/MIT",
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
        "author": {"@type": "Person", "name": "Ahmed Laban"},
    }
    return page("whyfull: find out why your Linux disk is full",
                "whyfull explains why a Linux disk is full: deleted files still held open, Docker, the systemd "
                "journal, old kernels, logs and caches, each with the command that frees it. Plus guides for "
                "fixing each cause by hand.", "", body, jsonld)


def build_guide(g, guides):
    md = markdown.Markdown(extensions=["fenced_code", "tables", "toc"])
    content = md.convert(g["body"])
    body = """<article class="guide">
  <h1>{title}</h1>
  <p class="jump">In a hurry? <a href="#whyfull">whyfull checks for this and every other common cause</a> in one command.</p>
  {content}
  {aside}
</article>
<section class="more">
  <h2>More guides</h2>
  {more}
</section>""".format(title=esc(g["title"]), content=content, aside=whyfull_aside(),
                     more=guide_list(guides, skip=g["slug"]))
    jsonld = {
        "@context": "https://schema.org", "@type": "TechArticle", "headline": g["title"],
        "description": g["description"], "url": "%s%sguides/%s/" % (SITE, BASE, g["slug"]),
        "datePublished": "2026-11-02", "dateModified": TODAY,
        "author": {"@type": "Person", "name": "Ahmed Laban"},
        "about": "Linux disk space",
    }
    return page(g["title"], g["description"], "guides/%s/" % g["slug"], body, jsonld)


def write(path, text):
    full = os.path.join(OUT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(text)


def main():
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    gdir = os.path.join(HERE, "guides")
    order = ["free-up-disk-space-ubuntu-server", "df-full-du-does-not-add-up", "deleted-files-still-using-space", "docker-disk-space",
             "kubernetes-node-disk-full", "journalctl-disk-usage", "no-space-left-on-device-but-df-shows-free-space",
             "var-log-full", "boot-full-remove-old-kernels", "mysql-binary-logs-filling-disk", "podman-disk-space"]
    found = {os.path.splitext(n)[0] for n in os.listdir(gdir) if n.endswith(".md")}
    slugs = [s for s in order if s in found] + sorted(found - set(order))
    guides = [read_guide(os.path.join(gdir, s + ".md")) for s in slugs]

    write("index.html", build_index(guides))
    for g in guides:
        write("guides/%s/index.html" % g["slug"], build_guide(g, guides))

    # IndexNow key (Bing, Yandex): lets the site announce new and changed pages.
    keys = [n for n in os.listdir(HERE) if re.match(r"^[0-9a-f]{32}\.txt$", n)]
    for name in ["style.css", "copy.js", "favicon.svg", "og.png"] + keys:
        src = os.path.join(HERE, name)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(OUT, name))
    shutil.copy(os.path.join(ROOT, "docs", "demo.svg"), os.path.join(OUT, "demo.svg"))

    urls = [SITE + BASE] + ["%s%sguides/%s/" % (SITE, BASE, g["slug"]) for g in guides]
    write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n'
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "".join("  <url><loc>%s</loc><lastmod>%s</lastmod></url>\n" % (u, TODAY) for u in urls)
          + "</urlset>\n")
    write("robots.txt", "User-agent: *\nAllow: /\nSitemap: %s%ssitemap.xml\n" % (SITE, BASE))
    print("built %d pages into %s" % (len(urls), os.path.relpath(OUT)))


if __name__ == "__main__":
    main()
