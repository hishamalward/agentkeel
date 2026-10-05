"""agentkeel core: the starter pages and the shared stylesheet that `task.py new` writes.

A starter is the thin page contract with places to fill, not a layout to keep: an audit or a
mockup can replace everything below the header. Each page links ./keel.css for the common look
and may add its own <style> for a bespoke layout.
"""

KEEL_CSS = """/* keel.css: the shared look of this repository's docs/ pages. Pages link it as ./keel.css
   and may add their own styles. Change it with care: every page uses it. */
:root {
  --bg: #fbfaf7; --surface: #ffffff; --ink: #1d1f23; --muted: #5d6470; --line: #e3e0d8;
  --accent: #2f5bd3; --ok: #1f7a4d; --warn: #9a6100; --bad: #b3261e; --code: #f3f1ec;
  --radius: 10px; --measure: 46rem;
  font: 16px/1.6 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #15171b; --surface: #1d2025; --ink: #e8e6e1; --muted: #a2a8b3; --line: #31353d;
    --accent: #8aa8ff; --ok: #5cc28f; --warn: #e0a84a; --bad: #f08a80; --code: #262a31;
  }
}
:root[data-theme="dark"] {
  --bg: #15171b; --surface: #1d2025; --ink: #e8e6e1; --muted: #a2a8b3; --line: #31353d;
  --accent: #8aa8ff; --ok: #5cc28f; --warn: #e0a84a; --bad: #f08a80; --code: #262a31;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); }
main { max-width: var(--measure); margin: 0 auto; padding: 2.5rem 1rem 4rem; }
header.page { border-bottom: 1px solid var(--line); margin-bottom: 2rem; padding-bottom: 1rem; }
header.page .kicker { color: var(--muted); font-size: .85rem; letter-spacing: .04em; text-transform: uppercase; }
h1 { font-size: 2rem; line-height: 1.2; margin: .3rem 0 .5rem; }
h2 { font-size: 1.3rem; margin: 2.4rem 0 .6rem; }
h3 { font-size: 1.05rem; margin: 1.6rem 0 .4rem; }
p, li { max-width: var(--measure); }
a { color: var(--accent); }
code, pre { font: .9em/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; background: var(--code); border-radius: 5px; }
code { padding: .1em .35em; }
pre { padding: .8rem 1rem; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: .95rem; display: block; overflow-x: auto; }
th, td { text-align: left; vertical-align: top; padding: .5rem .6rem; border-bottom: 1px solid var(--line); }
th { color: var(--muted); font-weight: 600; }
section { margin: 0 0 1.5rem; }
.card, section[data-keel-boundary], section[data-keel-transient], .state-now {
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 1rem 1.2rem;
}
section[data-keel-boundary] { border-left: 4px solid var(--accent); }
.card > h2:first-child, .state-now > h2:first-child, section[data-keel-boundary] > h2:first-child,
section[data-keel-transient] > h2:first-child { margin-top: 0; }
section[data-keel-transient] { border-left: 4px solid var(--warn); }
.state-now dl { display: grid; grid-template-columns: max-content 1fr; gap: .3rem 1rem; margin: 0; }
.state-now dt { color: var(--muted); }
.state-now dd { margin: 0; }
.tag { display: inline-block; font-size: .8rem; padding: .05rem .5rem; border-radius: 999px; border: 1px solid var(--line); color: var(--muted); }
.tag.ok { color: var(--ok); border-color: currentColor; }
.tag.warn { color: var(--warn); border-color: currentColor; }
.tag.bad { color: var(--bad); border-color: currentColor; }
.muted, small { color: var(--muted); }
.grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); }
img, svg, video { max-width: 100%; height: auto; }
header.page .brand { display: inline-flex; align-items: center; gap: .55rem; margin-bottom: .9rem; color: var(--ink); font-weight: 650; text-decoration: none; }
header.page .brand img { width: 2.2rem; height: 2.2rem; }
.lede { font-size: 1.1rem; }
nav.toc { display: flex; flex-wrap: wrap; gap: .3rem 1rem; margin-top: .9rem; font-size: .92rem; }
.callout { background: var(--surface); border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: var(--radius); padding: .8rem 1rem; }
.flow { display: grid; gap: .6rem; grid-template-columns: repeat(auto-fit, minmax(9.5rem, 1fr)); margin: 1rem 0; padding: 0; list-style: none; counter-reset: step; }
.flow > li { max-width: none; background: var(--surface); border: 1px solid var(--line); border-top: 3px solid var(--line); border-radius: var(--radius); padding: .7rem .8rem; font-size: .92rem; counter-increment: step; }
.flow > li::before { content: counter(step); display: block; color: var(--muted); font: 600 .75rem ui-monospace, Menlo, monospace; }
.flow > li b { display: block; }
.flow > li.human { border-top-color: var(--accent); }
.flow > li.ai { border-top-color: var(--ok); }
"""

_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="keel.css">
</head>
<body>
<main>
<header class="page">
  <div class="kicker">{kicker} &middot; created {date}</div>
  <h1>{title}</h1>
</header>
"""

_FOOT = """</main>
</body>
</html>
"""

STATE = """
<section class="state-now" id="state-now">
  <h2>State now</h2>
  <dl>
    <dt>Implementation</dt><dd>Not started.</dd>
    <dt>Release</dt><dd>Not released.</dd>
    <dt>External checks</dt><dd>None yet. Name the source and the date checked for each.</dd>
  </dl>
</section>

<section id="behavior">
  <h2>Current behavior and constraints</h2>
  <p>What is true now, in the present tense. Rewrite this when the feature changes; link the code
  or config that defines a value instead of copying the value.</p>
</section>

<section id="remaining">
  <h2>Remaining scope</h2>
  <p>Outstanding outcomes and what they depend on. Update in place as phases land.</p>
</section>

<section id="limitations">
  <h2>Current limitations and open decisions</h2>
  <ul><li>What is unresolved now and what it affects.</li></ul>
</section>

<section id="verification">
  <h2>Verification</h2>
  <p>Concise evidence for the claims above: the check, its result, the revision it ran on.</p>
</section>

<section data-keel-transient="working" id="working">
  <h2>Working</h2>
  <p>This phase only: the plan as a table (task, files, check), progress, next action.
  Overwrite it; never append a log. <code>task.py finish</code> removes it before main moves.</p>
</section>
"""

PROJECT = """
<section id="how-to-read">
  <p>The project canon: the repo-wide rules that apply now, each with its reason when the reason
  still helps. A feature's own rules live on its state page; this page links to it instead of
  copying it. Agent instructions live in AGENTS.md. Git keeps every earlier version.</p>
</section>

<section id="product">
  <h2>Product</h2>
  <p>One rule per paragraph or row, in the present tense.</p>
</section>

<section id="architecture">
  <h2>Architecture</h2>
  <p>Platform, data and hosting decisions that apply across features.</p>
</section>

<section id="working-rules">
  <h2>How work ships</h2>
  <p>Shipping, review and release rules that are not already enforced by the guards.</p>
</section>
"""

REFERENCE = """
<section id="summary">
  <p>One subject, owned here: a shared rule or a runbook. Pages that rely on it link here.</p>
</section>

<section id="rules">
  <h2>Rules</h2>
  <p>The current rule, in the present tense, with its reason when the reason still helps.</p>
</section>
"""

AUDIT = """
<section id="verdict" class="card">
  <h2>Verdict</h2>
  <p>The latest conclusion, and the revision it inspected.</p>
</section>

<section id="findings">
  <h2>Findings</h2>
  <p>One finding per block: what was seen, why it matters, the fix, the check that proves it.</p>
</section>

<section id="evidence">
  <h2>Evidence</h2>
  <p>What was run or read, and its limits.</p>
</section>
"""

MOCKUP = """
<section id="question">
  <p>The design question, and the state page it belongs to.</p>
</section>

<section id="options" class="grid">
  <div class="card"><h3>Current</h3><p>What exists now.</p></div>
  <div class="card"><h3>Proposed</h3><p>The proposal.</p></div>
</section>
"""

BOUNDARY = """
<section data-keel-boundary id="boundary">
  <h2>Agreed boundary</h2>
  <h3>Outcome</h3>
  <p>What will be true when this is done.</p>
  <h3>Constraints</h3>
  <ul><li>What must hold.</li></ul>
  <h3>Acceptance checks</h3>
  <ul><li>A check that proves the outcome.</li></ul>
  <h3>Files</h3>
  <p>Changes:</p>
  <ul data-keel-changes><li><code>src/feature/</code></li></ul>
  <p>Must not change:</p>
  <ul data-keel-must-not><li><code>src/auth/</code></li></ul>
</section>

"""

BODIES = {"state": STATE, "reference": REFERENCE, "audit": AUDIT, "mockup": MOCKUP, "project": PROJECT}
KICKERS = {"state": "Feature state", "reference": "Reference", "audit": "Audit", "mockup": "Mockup",
           "project": "Project canon"}


def page(kind, title, date, boundary=False):
    """A starter page: kind is state, reference, audit, mockup, or project (the project canon).
    `boundary` adds the section the human approves (size large): outcome, constraints, checks."""
    import html
    body = BODIES[kind]
    if boundary:
        body = body.replace('<section id="remaining">', BOUNDARY.lstrip("\n") + '<section id="remaining">', 1) \
            if '<section id="remaining">' in body else body + BOUNDARY
    return _HEAD.format(title=html.escape(title), kicker=KICKERS[kind], date=date) + body + _FOOT
