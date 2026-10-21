#!/usr/bin/env node
// Generate authored page variants from a trusted local HTML shell and manifest.
import fs from 'node:fs/promises';
import path from 'node:path';

const options = {};
for (let i = 2; i < process.argv.length; i++) {
  const name = process.argv[i];
  if (name === '--help') {
    console.log('node scene-page-generator.mjs --shell shell.html --pages pages.json --out dist --site-url https://example.com');
    process.exit(0);
  }
  if (!['--shell', '--pages', '--out', '--site-url'].includes(name) || !process.argv[i + 1] || options[name]) throw new Error(`Invalid or duplicate option: ${name}`);
  options[name] = process.argv[++i];
}
for (const name of ['--shell', '--pages', '--out', '--site-url']) if (!options[name]) throw new Error(`Missing ${name}`);
const site = new URL(options['--site-url']);
if (!['http:', 'https:'].includes(site.protocol) || site.pathname !== '/' || site.search || site.hash || site.username || site.password) throw new Error('--site-url must be an HTTP(S) origin');
const origin = site.origin;
const shell = await fs.readFile(options['--shell'], 'utf8');
const pages = JSON.parse(await fs.readFile(options['--pages'], 'utf8'));
if (!Array.isArray(pages) || !pages.length) throw new Error('Manifest must be a nonempty array');
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const seen = new Set();
// Validate and render everything before creating output files.
const rendered = pages.map(page => {
  if (typeof page.path !== 'string' || !/^\/(?:[a-z0-9]+(?:-[a-z0-9]+)*(?:\/[a-z0-9]+(?:-[a-z0-9]+)*)*)?$/.test(page.path)) throw new Error(`Unsafe path: ${page.path}`);
  if (seen.has(page.path)) throw new Error(`Duplicate page path: ${page.path}`);
  seen.add(page.path);
  for (const field of ['title', 'heading', 'description', 'body']) if (typeof page[field] !== 'string' || !page[field].trim()) throw new Error(`Missing ${field}: ${page.path}`);
  const url = origin + page.path;
  const graph = [{ '@type': 'WebPage', '@id': url + '#page', url, name: page.title, description: page.description }];
  if (page.path === '/') graph.push({ '@type': 'Organization', '@id': origin + '/#org', name: page.title, url });
  const jsonld = JSON.stringify({'@context':'https://schema.org', '@graph':graph}).replace(/[<>&]/g, c => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`);
  const values = {'site.url':escape(origin), 'page.url':escape(url), 'page.title':escape(page.title), 'page.heading':escape(page.heading), 'page.description':escape(page.description), 'page.body':page.body, 'jsonld':jsonld};
  const html = shell.replace(/\{\{\s*([a-z.]+)\s*\}\}/g, (_, key) => {
    if (!(key in values)) throw new Error(`Unknown shell token: ${key}`);
    return values[key];
  });
  if (/\{\{[^}]+\}\}/.test(html)) throw new Error('Unresolved shell token');
  return {file:page.path === '/' ? 'index.html' : page.path.slice(1) + '.html', url, html};
});
const output = path.resolve(options['--out']);
for (const item of rendered) {
  const filename = path.join(output, item.file);
  await fs.mkdir(path.dirname(filename), {recursive:true});
  await fs.writeFile(filename, item.html);
}
const sitemap = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + rendered.map(item => `  <url><loc>${escape(item.url)}</loc></url>`).join('\n') + '\n</urlset>\n';
await fs.writeFile(path.join(output, 'sitemap.xml'), sitemap);
await fs.writeFile(path.join(output, 'sitemap-pages.xml'), sitemap);
console.log(`Generated ${rendered.length} authored pages and two matching sitemaps in ${output}`);
