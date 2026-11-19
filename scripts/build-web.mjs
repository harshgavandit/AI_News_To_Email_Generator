import { readdirSync, readFileSync, existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { build } from 'esbuild';

// Vercel serves these static assets directly alongside the Python application.
// Validate the deployable files without copying private repository files.
await build({
  entryPoints: ['scripts/botid-client.mjs'],
  outfile: 'public/botid-client.js',
  bundle: true,
  minify: true,
  define: { 'process.env.NODE_ENV': '"production"' },
});

for (const filename of readdirSync('public')) {
  if (filename.endsWith('.css')) {
    const css = readFileSync(resolve('public', filename), 'utf8');
    for (const match of css.matchAll(/url\(["']?(\/[^)"'?#]+)["']?\)/g)) {
      if (!existsSync(resolve('public', match[1].slice(1)))) {
        throw new Error(`Missing stylesheet asset ${match[1]} in ${filename}`);
      }
    }
  }
  if (filename.endsWith('.js')) {
    const result = spawnSync(process.execPath, ['--check', resolve('public', filename)], { stdio: 'inherit' });
    if (result.status !== 0) process.exit(result.status || 1);
  }
  if (!filename.endsWith('.html')) continue;
  const html = readFileSync(resolve('public', filename), 'utf8');
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
  if (new Set(ids).size !== ids.length) throw new Error(`Duplicate element IDs in ${filename}`);
  const entry = filename === 'index.html' ? ['app.js', /\$\("([^"\n]+)"\)/g] :
    filename === 'sources.html' ? ['sources.js', /element\("([^"\n]+)"\)/g] :
    filename === 'contribute.html' ? ['contribute.js', /byId\("([^"\n]+)"\)/g] :
    filename === 'privacy.html' ? ['privacy.js', /byId\("([^"\n]+)"\)/g] :
    filename === 'research.html' ? ['research.js', /byId\("([^"\n]+)"\)/g] :
    filename === 'inbox.html' ? ['reader-inbox.js', /byId\("([^"\n]+)"\)/g] :
    filename === 'development.html' ? ['development.js', /getElementById\("([^"\n]+)"\)/g] : null;
  if (entry) {
    const script = readFileSync(resolve('public', entry[0]), 'utf8');
    for (const match of script.matchAll(entry[1])) {
      if (!ids.includes(match[1])) throw new Error(`Missing element #${match[1]} referenced by ${entry[0]}`);
    }
  }
  for (const match of html.matchAll(/(?:src|href)="(\/[^"?#]+\.(?:js|css|svg|jpg|webp|png|html))"/g)) {
    if (match[1].startsWith('/_vercel/')) continue;
    if (!existsSync(resolve('public', match[1].slice(1)))) {
      throw new Error(`Missing static asset ${match[1]} in ${filename}`);
    }
  }
}
console.log('Production static assets validated successfully.');
