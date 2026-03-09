#!/usr/bin/env node
/**
 * deploy.js
 *
 * Interactive deployment helper for EducativeViewer.
 *
 * Usage:
 *   node deploy.js              — interactive menu
 *   node deploy.js local        — local dev server (download zip + prepare + next start)
 *   node deploy.js vercel       — Vercel production deploy (push env vars + deploy)
 *   node deploy.js env          — push .env.local variables to Vercel only
 *   node deploy.js upload <tag> — upload .next.zip to an existing GitHub release
 *   node deploy.js release <tag>— create a new GitHub release with .next.zip
 *   node deploy.js repo         — manage GitHub repo (view/change/push tag)
 */

'use strict';

const { execSync, spawnSync } = require('child_process');
const fs   = require('fs');
const path = require('path');
const readline = require('readline');

const ROOT     = __dirname;
const ZIP_PATH = path.join(ROOT, '.next.zip');

// ─── Helpers ─────────────────────────────────────────────────────────────────

function run(cmd, opts = {}) {
  console.log(`\n> ${cmd}`);
  const result = spawnSync(cmd, { shell: true, stdio: 'inherit', cwd: ROOT, ...opts });
  if (result.status !== 0) {
    console.error(`\n[ERROR] Command failed: ${cmd}`);
    process.exit(result.status ?? 1);
  }
}

function runCapture(cmd) {
  try {
    return execSync(cmd, { cwd: ROOT, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
  } catch {
    return null;
  }
}

function ask(rl, question) {
  return new Promise(resolve => rl.question(question, resolve));
}

function header(title) {
  const line = '─'.repeat(title.length + 4);
  console.log(`\n┌${line}┐`);
  console.log(`│  ${title}  │`);
  console.log(`└${line}┘`);
}

// ─── GitHub auth check ───────────────────────────────────────────────────────

function checkGitHubAuth() {
  header('GitHub Auth Check');
  // Use spawnSync with inherit so auth status prints directly and doesn't
  // interfere with the readline interface on Windows.
  const check = spawnSync('gh', ['auth', 'status'], {
    shell: true, stdio: ['ignore', 'pipe', 'pipe'], cwd: ROOT, encoding: 'utf8',
  });
  if (check.error || (check.status !== 0 && check.status !== null &&
      !((check.stdout || '') + (check.stderr || '')).includes('Logged in'))) {
    // Not installed
    if (check.error && check.error.code === 'ENOENT') {
      console.error('[ERROR] GitHub CLI (gh) is not installed or not on PATH.');
      console.error('        Install it from https://cli.github.com/');
      process.exit(1);
    }
    // Not authenticated
    console.log('[!] Not logged in to GitHub. Running gh auth login...');
    run('gh auth login');
  } else {
    const out = (check.stdout || '') + (check.stderr || '');
    const userMatch = out.match(/Logged in to [^\s]+ account ([^\s(]+)/);
    console.log(`[+] GitHub authenticated${userMatch ? ` as ${userMatch[1]}` : ''}`);
  }
}

// ─── Default repo check ──────────────────────────────────────────────────────

function ensureDefaultRepo(rl) {
  return new Promise(async resolve => {
    const current = runCapture('gh repo set-default --view');
    if (current && !current.includes('no default')) {
      console.log(`[+] Default repo: ${current}`);
      return resolve(current.trim());
    }
    console.log('[!] No default GitHub repo set.');
    const repo = await ask(rl, '    Enter repo (e.g. GhostXRJ/EducativeViewer): ');
    run(`gh repo set-default ${repo.trim()}`);
    resolve(repo.trim());
  });
}

// ─── Repo resolution (no auth required for public repos) ────────────────────

function detectRepoFromRemote() {
  const url = runCapture('git remote get-url origin');
  if (!url) return null;
  // Handles both https://github.com/owner/repo.git and git@github.com:owner/repo.git
  const m = url.match(/github\.com[/:]([^/\s]+\/[^/\s.]+)/);
  return m ? m[1].replace(/\.git$/, '') : null;
}

async function resolveRepo(rl) {
  const fromRemote = detectRepoFromRemote();
  if (fromRemote) {
    console.log(`[+] Using repo: ${fromRemote}`);
    return fromRemote;
  }
  // Try gh default without requiring login
  const ghDefault = runCapture('gh repo set-default --view');
  if (ghDefault && !ghDefault.includes('no default') && !ghDefault.includes('error')) {
    console.log(`[+] Using repo: ${ghDefault.trim()}`);
    return ghDefault.trim();
  }
  const repo = await ask(rl, '    Enter repo (e.g. GhostXRJ/EducativeViewer): ');
  return repo.trim();
}

// ─── Repo management ─────────────────────────────────────────────────────────

async function manageRepo(rl) {
  while (true) {
    header('GitHub Repo Management');

    const currentRepo   = runCapture('gh repo set-default --view') || '(none)';
    const remotes       = runCapture('git remote -v') || '(no remotes)';
    const currentBranch = runCapture('git branch --show-current') || '(unknown)';
    const localTags     = runCapture('git tag --list') || '';

    console.log(`\n  Current gh default repo : ${currentRepo}`);
    console.log(`  Current git branch      : ${currentBranch}`);
    console.log(`\n  Git remotes:\n${remotes.split('\n').map(l => '    ' + l).join('\n')}`);
    console.log(`\n  Local tags: ${localTags.split('\n').filter(Boolean).join(', ') || '(none)'}`);

    console.log('');
    console.log('  a) Change default gh repo');
    console.log('  b) Add / update a git remote');
    console.log('  c) Create a local git tag');
    console.log('  d) Push a local tag to remote');
    console.log('  e) Delete a local tag');
    console.log('  f) Delete a remote tag');
    console.log('  g) List GitHub releases');
    console.log('  h) Back to main menu');
    console.log('');

    const sub = await ask(rl, 'Choose [a-h]: ');

    switch (sub.trim().toLowerCase()) {
      case 'a': {
        const repo = await ask(rl, 'New default repo (e.g. GhostXRJ/EducativeViewer): ');
        run(`gh repo set-default ${repo.trim()}`);
        console.log(`[+] Default repo set to ${repo.trim()}`);
        break;
      }
      case 'b': {
        const name = await ask(rl, 'Remote name (e.g. origin): ');
        const url  = await ask(rl, 'Remote URL (e.g. https://github.com/User/Repo.git): ');
        const exists = runCapture(`git remote get-url ${name.trim()}`);
        if (exists) {
          run(`git remote set-url ${name.trim()} ${url.trim()}`);
          console.log(`[+] Updated remote '${name.trim()}'`);
        } else {
          run(`git remote add ${name.trim()} ${url.trim()}`);
          console.log(`[+] Added remote '${name.trim()}'`);
        }
        break;
      }
      case 'c': {
        const tag    = await ask(rl, 'Tag name (e.g. v1.0.0): ');
        const target = await ask(rl, 'Commit/branch to tag (leave blank for HEAD): ');
        const ref    = target.trim() || 'HEAD';
        run(`git tag ${tag.trim()} ${ref}`);
        console.log(`[+] Created local tag ${tag.trim()} at ${ref}`);
        break;
      }
      case 'd': {
        const tag    = await ask(rl, 'Tag name to push (e.g. v1.0.0): ');
        const remote = await ask(rl, 'Remote to push to (default: origin): ');
        run(`git push ${(remote.trim() || 'origin')} ${tag.trim()}`);
        console.log(`[+] Pushed tag ${tag.trim()}`);
        break;
      }
      case 'e': {
        const tag = await ask(rl, 'Local tag to delete: ');
        run(`git tag -d ${tag.trim()}`);
        break;
      }
      case 'f': {
        const tag    = await ask(rl, 'Remote tag to delete: ');
        const remote = await ask(rl, 'Remote (default: origin): ');
        run(`git push ${(remote.trim() || 'origin')} --delete ${tag.trim()}`);
        break;
      }
      case 'g': {
        const list = runCapture('gh release list --limit 20');
        console.log('\nGitHub releases:\n');
        console.log(list || '(none)');
        break;
      }
      case 'h':
      default:
        return;
    }
  }
}

// ─── Download zip from GitHub releases ───────────────────────────────────────

async function downloadZip(rl) {
  header('Download .next.zip from GitHub Releases');

  const repo = await resolveRepo(rl);

  // List ALL releases — works unauthenticated for public repos
  let releases = runCapture(`gh release list --repo "${repo}" --limit 100`);
  let latestTag = null;
  if (!releases) {
    // Fallback: GitHub REST API (no auth needed for public repos)
    console.log('[!] gh CLI unavailable or not authenticated, fetching via GitHub API...');
    const apiUrl = `https://api.github.com/repos/${repo}/releases?per_page=100`;
    const raw = process.platform === 'win32'
      ? runCapture(`powershell -Command "(Invoke-WebRequest -Uri '${apiUrl}' -UseBasicParsing).Content"`)
      : runCapture(`curl -sf "${apiUrl}"`);
    if (raw) {
      try {
        const parsed = JSON.parse(raw);
        if (parsed.length) latestTag = parsed[0].tag_name;
        releases = parsed.map(r => `${r.tag_name.padEnd(20)} ${r.name || ''}`).join('\n');
      } catch { /* ignore parse error */ }
    }
  } else {
    // gh release list output: first token of the first line is the latest tag
    const firstLine = releases.split('\n').find(l => l.trim());
    if (firstLine) latestTag = firstLine.trim().split(/\s+/)[0];
  }
  if (!releases) {
    console.error('[ERROR] Could not fetch releases. Check repo name and network connection.');
    process.exit(1);
  }

  console.log('\nAvailable releases:\n');
  console.log(releases);

  const prompt = latestTag
    ? `\nEnter release tag to download (default: ${latestTag}): `
    : '\nEnter release tag to download from (e.g. v1.0.0): ';
  const tagInput = (await ask(rl, prompt)).trim();
  const tagClean = tagInput || latestTag;
  if (!tagClean) {
    console.error('[ERROR] No tag provided and no latest release found.');
    process.exit(1);
  }
  console.log(`\n[*] Downloading .next.zip from release ${tagClean} ...`);

  // Try gh first (works without auth for public repos), fall back to direct URL
  const ghResult = spawnSync(
    `gh release download "${tagClean}" --repo "${repo}" --pattern "*.zip" --output "${ZIP_PATH}" --clobber`,
    { shell: true, stdio: ['ignore', 'pipe', 'pipe'], cwd: ROOT }
  );
  if (ghResult.status !== 0) {
    console.log('[!] gh download failed, falling back to direct URL download...');
    const url = `https://github.com/${repo}/releases/download/${tagClean}/.next.zip`;
    if (process.platform === 'win32') {
      run(`powershell -Command "Invoke-WebRequest -Uri '${url}' -OutFile '${ZIP_PATH}'"`);
    } else {
      run(`curl -L "${url}" -o "${ZIP_PATH}"`);
    }
  }

  console.log(`[+] Saved to ${ZIP_PATH}`);
  return tagClean;
}

// ─── Prepare build output ────────────────────────────────────────────────────

function prepareBuild() {
  header('Preparing Build Output');
  if (!fs.existsSync(ZIP_PATH)) {
    console.error(`[ERROR] ${ZIP_PATH} not found. Download the zip first.`);
    process.exit(1);
  }
  run('node prepare-deploy.js');
}

// ─── Push env vars to Vercel ────────────────────────────────────────────────

function parseEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return {};
  const vars = {};
  for (const raw of fs.readFileSync(filePath, 'utf8').split('\n')) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    // Strip surrounding quotes from value
    let val = line.slice(eq + 1).trim();
    if ((val.startsWith('"') && val.endsWith('"')) ||
        (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }
    vars[key] = val;
  }
  return vars;
}

async function uploadEnvVars(rl) {
  header('Push Env Vars to Vercel');

  const envPath = path.join(ROOT, '.env.local');
  if (!fs.existsSync(envPath)) {
    console.error('[ERROR] .env.local not found. Create it from .env.local.example first.');
    process.exit(1);
  }

  // Ensure Vercel CLI and linked project
  const vercelVersion = runCapture('vercel --version');
  if (!vercelVersion) {
    console.log('[!] Vercel CLI not found. Installing...');
    run('npm install -g vercel');
  }
  const vercelProject = path.join(ROOT, '.vercel', 'project.json');
  if (!fs.existsSync(vercelProject)) {
    console.log('[!] No .vercel/project.json found. Running vercel link...');
    run('vercel link');
  }

  const vars = parseEnvFile(envPath);
  // VERCEL_ENV is set automatically by Vercel — never push it
  delete vars['VERCEL_ENV'];

  const keys = Object.keys(vars);
  if (keys.length === 0) {
    console.log('[!] No variables found in .env.local.');
    return;
  }

  console.log(`\n[*] Found ${keys.length} variable(s): ${keys.join(', ')}`);
  const envTarget = await ask(rl, 'Push to which Vercel environment? [production/preview/development] (default: production): ');
  const target = envTarget.trim() || 'production';

  let pushed = 0;
  for (const [key, value] of Object.entries(vars)) {
    process.stdout.write(`    ${key} ... `);
    // Remove existing value first (ignore error if not set)
    runCapture(`vercel env rm "${key}" ${target} --yes`);
    // Add new value by piping via stdin
    const result = spawnSync(
      `vercel env add "${key}" ${target}`,
      { shell: true, input: value, stdio: ['pipe', 'pipe', 'pipe'], cwd: ROOT }
    );
    if (result.status === 0) {
      console.log('OK');
      pushed++;
    } else {
      console.log(`FAILED (${(result.stderr || '').toString().trim()})`);
    }
  }

  console.log(`\n[+] Pushed ${pushed}/${keys.length} variable(s) to Vercel ${target}.`);
}

// ─── Manage Vercel ───────────────────────────────────────────────────────────

async function manageVercel(rl) {
  while (true) {
    header('Vercel Management');

    const vercelVersion = runCapture('vercel --version') || '(not installed)';
    const vercelProject = path.join(ROOT, '.vercel', 'project.json');
    let linkedProject = '(not linked)';
    if (fs.existsSync(vercelProject)) {
      const p = JSON.parse(fs.readFileSync(vercelProject, 'utf8'));
      linkedProject = `projectId=${p.projectId}  orgId=${p.orgId}`;
    }

    console.log(`\n  Vercel CLI        : ${vercelVersion}`);
    console.log(`  Linked project    : ${linkedProject}`);
    console.log('');
    console.log('  a) Link to a Vercel project (vercel link)');
    console.log('  b) List environment variables');
    console.log('  c) Push .env.local vars to Vercel');
    console.log('  d) Pull env vars from Vercel → .env.local');
    console.log('  e) Add a single env var');
    console.log('  f) Remove a single env var');
    console.log('  g) List deployments');
    console.log('  h) Open project dashboard in browser');
    console.log('  i) Back to main menu');
    console.log('');

    const sub = await ask(rl, 'Choose [a-i]: ');

    switch (sub.trim().toLowerCase()) {
      case 'a':
        run('vercel link');
        break;
      case 'b': {
        const envTarget = await ask(rl, 'Environment [production/preview/development] (default: production): ');
        const t = envTarget.trim() || 'production';
        run(`vercel env ls ${t}`);
        break;
      }
      case 'c':
        await uploadEnvVars(rl);
        break;
      case 'd': {
        const envTarget = await ask(rl, 'Pull from environment [production/preview/development] (default: production): ');
        const t = envTarget.trim() || 'production';
        const outFile = await ask(rl, 'Output file (default: .env.vercel): ');
        const out = outFile.trim() || '.env.vercel';
        run(`vercel env pull ${out} --environment ${t} --yes`);
        console.log(`[+] Pulled Vercel env vars into ${out} (not .env.local — that is for application keys only)`);
        break;
      }
      case 'e': {
        const key = await ask(rl, 'Variable name: ');
        const val = await ask(rl, 'Value: ');
        const envTarget = await ask(rl, 'Environment [production/preview/development] (default: production): ');
        const t = envTarget.trim() || 'production';
        runCapture(`vercel env rm "${key.trim()}" ${t} --yes`);
        const result = spawnSync(`vercel env add "${key.trim()}" ${t}`, {
          shell: true, input: val, stdio: ['pipe', 'inherit', 'inherit'], cwd: ROOT,
        });
        if (result.status === 0) console.log(`[+] Added ${key.trim()} to ${t}`);
        break;
      }
      case 'f': {
        const key = await ask(rl, 'Variable name to remove: ');
        const envTarget = await ask(rl, 'Environment [production/preview/development] (default: production): ');
        const t = envTarget.trim() || 'production';
        run(`vercel env rm "${key.trim()}" ${t} --yes`);
        break;
      }
      case 'g':
        run('vercel ls');
        break;
      case 'h': {
        if (fs.existsSync(vercelProject)) {
          const p = JSON.parse(fs.readFileSync(vercelProject, 'utf8'));
          const url = `https://vercel.com/dashboard`;
          console.log(`[+] Opening ${url}`);
          run(process.platform === 'win32' ? `start ${url}` : `open ${url}`);
        } else {
          console.log('[!] Project not linked. Run option (a) first.');
        }
        break;
      }
      case 'i':
      default:
        return;
    }
  }
}

// ─── Env var checker / prompt ────────────────────────────────────────────────

async function checkAndPromptEnvVars(rl) {
  header('Environment Variable Check');

  const envPath     = path.join(ROOT, '.env.local');
  const examplePath = path.join(ROOT, '.env.local.example');

  // Bootstrap .env.local from example if missing
  if (!fs.existsSync(envPath)) {
    if (fs.existsSync(examplePath)) {
      fs.copyFileSync(examplePath, envPath);
      console.log('[+] Created .env.local from .env.local.example');
    } else {
      console.log('[!] No .env.local or .env.local.example found. Skipping env check.');
      return;
    }
  }

  const vars        = parseEnvFile(envPath);
  const exampleVars = fs.existsSync(examplePath) ? parseEnvFile(examplePath) : {};

  // All keys from both files (example first so order is consistent)
  const allKeys = [...new Set([...Object.keys(exampleVars), ...Object.keys(vars)])];

  const skipKeys = new Set();

  const isPlaceholder = (val) =>
    !val || val.toLowerCase().includes('your-') || val === 'change-me' || val === 'CHANGEME';

  let changed = false;
  for (const key of allKeys) {
    if (skipKeys.has(key)) continue;
    const current = vars[key];
    if (isPlaceholder(current)) {
      // Placeholder — must be configured, no sensible default to fall back on
      console.log(`\n[!] ${key} is not configured`);
      let val = '';
      while (!val) {
        val = (await ask(rl, `    Enter value for ${key}: `)).trim();
        if (!val) console.log(`    [!] Value cannot be empty.`);
      }
      vars[key] = val;
      changed = true;
    } else {
      // Already set — offer to replace, keep current if user presses Enter
      const input = (await ask(rl, `[?] ${key} = "${current}"\n    New value (Enter to keep): `)).trim();
      if (input) {
        vars[key] = input;
        changed = true;
        console.log(`    [+] Updated.`);
      } else {
        console.log(`    [+] Kept.`);
      }
    }
  }

  if (changed) {
    // Rewrite .env.local, preserving comments from the example template
    let out = '';
    if (fs.existsSync(examplePath)) {
      for (const line of fs.readFileSync(examplePath, 'utf8').split('\n')) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith('#')) { out += line + '\n'; continue; }
        const eq = trimmed.indexOf('=');
        if (eq === -1) { out += line + '\n'; continue; }
        const key = trimmed.slice(0, eq).trim();
        out += key in vars ? `${key}=${vars[key]}\n` : `${line}\n`;
      }
      // Append any extra keys not present in the example
      for (const [k, v] of Object.entries(vars)) {
        if (!(k in exampleVars)) out += `${k}=${v}\n`;
      }
    } else {
      out = Object.entries(vars).map(([k, v]) => `${k}=${v}`).join('\n') + '\n';
    }
    fs.writeFileSync(envPath, out, 'utf8');
    console.log('\n[+] .env.local saved.');
  } else {
    console.log('\n[+] All environment variables look good.');
  }
}

// ─── Deployment modes ────────────────────────────────────────────────────────

async function deployLocal(rl) {
  await checkAndPromptEnvVars(rl);
  header('Starting Local Server');
  console.log('[*] Starting Next.js server on http://localhost:3000 ...');
  run('npx next start');
}

function checkVercelSetup() {
  header('Vercel Setup Check');

  // Check vercel CLI
  const vercelVersion = runCapture('vercel --version');
  if (!vercelVersion) {
    console.log('[!] Vercel CLI not found. Installing...');
    run('npm install -g vercel');
  } else {
    console.log(`[+] Vercel CLI: ${vercelVersion}`);
  }

  // Check .vercel/project.json
  const vercelProject = path.join(ROOT, '.vercel', 'project.json');
  if (!fs.existsSync(vercelProject)) {
    console.log('[!] No .vercel/project.json found. Running vercel link...');
    run('vercel link');
  } else {
    const proj = JSON.parse(fs.readFileSync(vercelProject, 'utf8'));
    console.log(`[+] Linked to Vercel project: ${proj.projectId}`);
  }
}

async function deployVercelFull(rl) {
  await checkAndPromptEnvVars(rl);
  await checkVercelSetup(rl);
  await uploadEnvVars(rl);
  header('Deploying to Vercel');
  run('vercel deploy --prod');
}

function deployVercel() {
  checkVercelSetup();
  run('vercel deploy --prod');
}

// ─── GitHub release helpers ──────────────────────────────────────────────────

async function uploadToRelease(rl, tagArg) {
  header('Upload .next.zip to GitHub Release');

  if (!fs.existsSync(ZIP_PATH)) {
    console.error(`[ERROR] ${ZIP_PATH} not found. Download or build the zip first.`);
    process.exit(1);
  }

  const tag = tagArg || await ask(rl, 'Enter release tag to upload to (e.g. v1.0.0): ');
  run(`gh release upload "${tag.trim()}" "${ZIP_PATH}" --clobber`);
  console.log(`[+] Uploaded .next.zip to release ${tag.trim()}`);
}

async function createRelease(rl, tagArg) {
  header('Create GitHub Release');

  if (!fs.existsSync(ZIP_PATH)) {
    console.error(`[ERROR] ${ZIP_PATH} not found. Download or build the zip first.`);
    process.exit(1);
  }

  const tag   = tagArg || await ask(rl, 'Enter new release tag (e.g. v1.0.1): ');
  const title = await ask(rl, `Release title [${tag.trim()}]: `);
  const notes = await ask(rl, 'Release notes (leave blank for none): ');

  run(`gh release create "${tag.trim()}" "${ZIP_PATH}" --title "${(title || tag).trim()}" --notes "${notes.trim()}" --target main`);
  console.log(`[+] Release ${tag.trim()} created with .next.zip`);
}

// ─── Interactive menu (loops until Exit) ─────────────────────────────────────

async function interactiveMenu(rl) {
  while (true) {
  console.log('\n┌──────────────────────────────┐');
  console.log('│   EducativeViewer Deployer   │');
  console.log('└──────────────────────────────┘');
  console.log('');
  console.log('  1) Download zip + push env vars + deploy to Vercel');
  console.log('  2) Download zip + run locally');
  console.log('  3) Push env vars + deploy to Vercel (use existing .next.zip)');
  console.log('  4) Run locally (use existing .next.zip)');
  console.log('  5) Push .env.local variables to Vercel only');
  console.log('  6) Create new GitHub Release with .next.zip');
  console.log('  7) Upload .next.zip to existing release');
  console.log('  8) Manage GitHub repo / tags');
  console.log('  9) Manage Vercel');
  console.log('  0) Exit');
  console.log('');

  const choice = await ask(rl, 'Choose an option [0-9]: ');

  switch (choice.trim()) {
    case '1':
      await downloadZip(rl);  // resolves repo without requiring auth
      prepareBuild();
      await deployVercelFull(rl);
      break;
    case '2':
      await downloadZip(rl);  // resolves repo without requiring auth
      prepareBuild();
      await deployLocal(rl);
      break;
    case '3':
      prepareBuild();
      await deployVercelFull(rl);
      break;
    case '4':
      prepareBuild();
      await deployLocal(rl);
      break;
    case '5':
      await uploadEnvVars(rl);
      break;
    case '6':
      checkGitHubAuth();
      await ensureDefaultRepo(rl);
      await createRelease(rl);
      break;
    case '7':
      checkGitHubAuth();
      await ensureDefaultRepo(rl);
      await uploadToRelease(rl);
      break;
    case '8':
      checkGitHubAuth();
      await manageRepo(rl);
      break;
    case '9':
      await manageVercel(rl);
      break;
    case '0':
      console.log('Bye.');
      return;
    default:
      console.log('[!] Invalid choice, please enter 0-9.');
      break;
  }
  } // end while
}

// ─── Entry point ─────────────────────────────────────────────────────────────

async function main() {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

  const cmd = process.argv[2];
  const arg = process.argv[3];

  try {
    if (!cmd) {
      await interactiveMenu(rl);
    } else if (cmd === 'local') {
      await downloadZip(rl);  // resolves repo without requiring auth
      prepareBuild();
      await deployLocal(rl);
    } else if (cmd === 'vercel') {
      await downloadZip(rl);  // resolves repo without requiring auth
      prepareBuild();
      await deployVercelFull(rl);
    } else if (cmd === 'env') {
      await uploadEnvVars(rl);
    } else if (cmd === 'repo') {
      checkGitHubAuth();
      await manageRepo(rl);
    } else if (cmd === 'vercel-manage') {
      await manageVercel(rl);
    } else if (cmd === 'upload') {
      checkGitHubAuth();
      await ensureDefaultRepo(rl);
      await uploadToRelease(rl, arg);
    } else if (cmd === 'release') {
      checkGitHubAuth();
      await ensureDefaultRepo(rl);
      await createRelease(rl, arg);
    } else {
      console.error(`Unknown command: ${cmd}`);
      console.error('Usage: node deploy.js [local|vercel|upload <tag>|release <tag>]');
      process.exit(1);
    }
  } finally {
    rl.close();
  }
}

main().catch(err => {
  console.error('[FATAL]', err.message);
  process.exit(1);
});
