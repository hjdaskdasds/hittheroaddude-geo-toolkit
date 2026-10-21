# GEO publishing toolkit

Two dependency-free command-line tools extracted from a working editorial publishing workflow. One renders **authored** page variants through a shared shell; the other checks a built site locally or reads its public production pages. They do not write articles, submit to search engines, deploy a site, or guarantee rankings or AI citations.

## Requirements

Node.js 22+ for the generator; Python 3.9+ for the checker. Both use only their standard libraries. No API key or account is needed.

## Generate pages from a shell

```sh
node scene-page-generator.mjs \
  --shell examples/shell.html --pages examples/pages.json \
  --out dist --site-url https://example.test
```

The manifest is an array with `path`, `title`, `heading`, `description`, and `body`. Text fields are HTML-escaped. `body` is trusted authored HTML: never feed it untrusted submissions. The shell supports `{{site.url}}`, `{{page.url}}`, `{{page.title}}`, `{{page.heading}}`, `{{page.description}}`, `{{page.body}}`, and `{{jsonld}}`. The generator validates all entries before writing, rejects duplicate/unsafe paths, escapes JSON-LD against script termination, and writes matching `sitemap.xml` and `sitemap-pages.xml` files. Supply genuinely distinct, useful content for each page.

## Run all six publishing checks

A local example, with an explicit recorded comparison fixture:

```sh
python3 publish_check.py --local --dir dist \
  --site-url https://example.test --reference-url https://reference.example \
  --reference-file examples/reference.html \
  --require-text 'Review before publishing' --forbid-text 'unverified claim'
```

For production, omit `--local` and `--reference-file`, and supply the real public origins. `--dir` remains the expected built-page inventory; the HTML/XML under test is fetched live. Set `--output /path/to/evidence` to preserve evidence in a chosen directory. `bash publish-check.sh ...` is a wrapper for the same command.

| Stage | What it verifies |
|---|---|
| 1. Status | Sitemap URLs and expected public HTML documents return 200. |
| 2. Schema | Every JSON-LD block parses; the homepage has an Organization. |
| 3. Internal targets | HTML links, linked resources and fragments resolve, including navigation/footer and noindex utility pages. |
| 4. Facts | Required phrases occur in body copy; forbidden phrases are absent from complete HTML, including schema and hidden nodes. |
| 5. Overlap | Directional 8-gram coverage of homepage main text is strictly below the configured threshold (default 15%). |
| 6. Inventory | Both sitemap sets agree and match indexable built HTML; optional RSS checks can be enabled. |

Optional RSS: `--feed-path /feed.xml --feed-min-items 14`. Optional overlap threshold: `--max-overlap 15`. The checker stops with exit status 1 at the first failing stage. Public HTTP requests have timeouts and are **not retried**; a blocking security challenge stops the run. A normal network fetch cannot act as a logged-in browser or solve a CAPTCHA.

### Reproduce the overlap number

The source is raw HTML `<main>` text, not a rendered browser screenshot. Remove nav/header/footer/aside, scripts/styles/noscript/template/textarea, and nodes marked `hidden` or `aria-hidden`. CSS-only visibility and runtime text are not executed. Decode entities, normalize curly apostrophes, Unicode-casefold, and tokenize with `\b\w+(?:'\w+)*\b`.

For each consecutive **8-token position in your homepage**, count a match if the identical tuple occurs anywhere in the comparison page's tuple set. Percentage = matched owned positions / all owned positions × 100. This is directional position coverage, **not** Jaccard or unique-window similarity. Reports save both HTML snapshots, extracted main text, token arrays, source labels, counts, and SHA256 hashes. The comparison page is measurement input only; do not copy its prose into generated pages.

### Limits

Internal checks cover HTML `a/link href`, media/script `src`, and video posters, including nav/footer. They do not execute JS, crawl CSS `url()`, test query-dependent product flows, audit external sites, or call authenticated APIs. The intentional `404.html` is excluded. This small audit is not an HTML conformance validator or a substitute for product acceptance testing. Fetch production only when you have authorization to audit it.

## Verify the tools

```sh
python3 -m unittest discover -s test -p 'test_*.py' -v
```

The tests use temporary fixtures, exercise successful generation and all six checks, verify a real broken link fails stage 3, enforce the fact guard inside JSON-LD, and reject unsafe or duplicate generator paths. No production website is changed.

MIT licensed; see [LICENSE](LICENSE).

Built for https://hittheroaddude.xyz — a one-photo meme video studio.
