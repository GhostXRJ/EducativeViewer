/**
 * prepare-deploy.js
 * Robust version of prepare-vercel.js.
 *
 * Handles builds from any OS:
 *   - Windows : appDir = D:\Users\...\project
 *   - macOS   : appDir = /Users/.../project
 *   - Linux   : appDir = /home/.../project
 *
 * Also handles ZIP files created by any OS tool:
 *   - Correctly parses data descriptors (macOS/Linux zip tools set flag bit 3,
 *     meaning sizes are written AFTER file data, not in the local file header)
 *   - Auto-detects the root folder name inside the ZIP (e.g. .next/, nextBuild/)
 *
 * Run : node prepare-deploy.js
 * Then: vercel deploy --prod
 */

const fs   = require('fs');
const path = require('path');
const zlib = require('zlib');

const ROOT        = __dirname;
const ZIP_PATH    = path.join(ROOT, '.next.zip');
const BUILD_DIR   = 'nextBuild';
const BUILD_PATH  = path.join(ROOT, BUILD_DIR);
const VERCEL_PATH = '/vercel/path0';

// ─── Step 1: Parse ZIP central directory for reliable metadata ────────────────
// The Central Directory at the end of the ZIP always has correct sizes,
// unlike local file headers which may be zeroed when data descriptors are used.

function parseCentralDirectory(buf) {
  // Find End of Central Directory record (signature 0x06054b50)
  let eocd = -1;
  for (let i = buf.length - 22; i >= 0; i--) {
    if (buf[i] === 0x50 && buf[i+1] === 0x4B &&
        buf[i+2] === 0x05 && buf[i+3] === 0x06) {
      eocd = i;
      break;
    }
  }
  if (eocd === -1) throw new Error('Not a valid ZIP file: EOCD not found');

  const cdOffset = buf.readUInt32LE(eocd + 16);
  const cdSize   = buf.readUInt32LE(eocd + 12);
  const entries  = [];

  let i = cdOffset;
  while (i < cdOffset + cdSize) {
    if (buf[i] !== 0x50 || buf[i+1] !== 0x4B ||
        buf[i+2] !== 0x01 || buf[i+3] !== 0x02) break;

    const compression      = buf.readUInt16LE(i + 10);
    const compressedSize   = buf.readUInt32LE(i + 20);
    const uncompressedSize = buf.readUInt32LE(i + 24);
    const fileNameLen      = buf.readUInt16LE(i + 28);
    const extraLen         = buf.readUInt16LE(i + 30);
    const commentLen       = buf.readUInt16LE(i + 32);
    const localHeaderOff   = buf.readUInt32LE(i + 42);
    const fileName         = buf.slice(i + 46, i + 46 + fileNameLen).toString('utf8')
                               .replace(/\\/g, '/');  // normalise Windows backslashes

    entries.push({ fileName, compression, compressedSize, uncompressedSize, localHeaderOff });
    i += 46 + fileNameLen + extraLen + commentLen;
  }
  return entries;
}

function extractEntry(buf, entry) {
  const lh = entry.localHeaderOff;
  if (buf[lh] !== 0x50 || buf[lh+1] !== 0x4B ||
      buf[lh+2] !== 0x03 || buf[lh+3] !== 0x04) {
    throw new Error(`Local header not found for ${entry.fileName}`);
  }
  const fileNameLen  = buf.readUInt16LE(lh + 26);
  const extraLen     = buf.readUInt16LE(lh + 28);
  const dataStart    = lh + 30 + fileNameLen + extraLen;
  const data         = buf.slice(dataStart, dataStart + entry.compressedSize);
  return entry.compression === 8 ? zlib.inflateRawSync(data) : data;
}

// ─── Step 2: Detect root folder in ZIP ───────────────────────────────────────

function detectZipRoot(entries) {
  for (const e of entries) {
    const parts = e.fileName.split('/');
    // Standard: entries like ".next/foo" or ".next/"
    if (parts.length >= 2 && parts[0]) return parts[0];
  }
  // Flat ZIP (no root folder prefix) — treat all entries as already under root
  return '';
}

// ─── Step 3: Extract ZIP → nextBuild/ ────────────────────────────────────────

if (!fs.existsSync(ZIP_PATH)) {
  console.error('[ERROR] .next.zip not found at ' + ZIP_PATH);
  process.exit(1);
}

console.log('[*] Reading ' + ZIP_PATH + ' ...');
const zipBuf  = fs.readFileSync(ZIP_PATH);
const entries = parseCentralDirectory(zipBuf);
console.log('[+] ZIP contains ' + entries.length + ' entries');

const zipRoot = detectZipRoot(entries);
if (zipRoot === null) {
  console.error('[ERROR] Could not detect root folder inside ZIP');
  process.exit(1);
}
if (zipRoot === '') {
  console.log('[+] ZIP has no root folder prefix (flat layout)');
} else {
  console.log('[+] Detected ZIP root folder: ' + zipRoot + '/');
}

console.log('[*] Cleaning ' + BUILD_DIR + '/ ...');
fs.rmSync(BUILD_PATH, { recursive: true, force: true });
console.log('[+] Cleaned');

let extracted = 0;
for (const entry of entries) {
  // Rewrite: <zipRoot>/foo/bar  ->  nextBuild/foo/bar
  // If zipRoot is '' (flat ZIP), just prepend BUILD_DIR
  const relative = zipRoot
    ? entry.fileName.replace(/^[^/]+\//, BUILD_DIR + '/')
    : BUILD_DIR + '/' + entry.fileName;
  const outPath  = path.join(ROOT, relative.replace(/\//g, path.sep));

  if (entry.fileName.endsWith('/')) {
    fs.mkdirSync(outPath, { recursive: true });
  } else {
    fs.mkdirSync(path.dirname(outPath), { recursive: true });
    const content = extractEntry(zipBuf, entry);
    fs.writeFileSync(outPath, content);
    extracted++;
  }
}
console.log('[+] Extracted ' + extracted + ' files into ' + BUILD_DIR + '/');

// ─── Step 4: Fix required-server-files.json ──────────────────────────────────
// Works regardless of original build OS:
// - Windows paths like D:\Users\...\project  -> /vercel/path0
// - macOS paths   like /Users/.../project    -> /vercel/path0
// - Linux paths   like /home/.../project     -> /vercel/path0
// All are replaced by directly setting the JSON fields on the parsed object.

const rsfPath = path.join(BUILD_PATH, 'required-server-files.json');
if (!fs.existsSync(rsfPath)) {
  console.error('[ERROR] required-server-files.json not found in extracted output');
  process.exit(1);
}

const rsf = JSON.parse(fs.readFileSync(rsfPath, 'utf8'));
const originalAppDir = rsf.appDir;

rsf.config.distDir              = BUILD_DIR;
rsf.config.distDirRoot          = BUILD_DIR;
rsf.config.outputFileTracingRoot = VERCEL_PATH;
if (rsf.config.turbopack) rsf.config.turbopack.root = VERCEL_PATH;
rsf.appDir = VERCEL_PATH;

// Fix files[] array — entries can use / or \ depending on build OS
rsf.files = rsf.files.map(p =>
  p.replace(/^[^/\\]+[/\\]/, BUILD_DIR + '/').replace(/\\/g, '/')
);

fs.writeFileSync(rsfPath, JSON.stringify(rsf, null, 2));
console.log('[+] Fixed required-server-files.json');
// console.log('    original appDir : ' + originalAppDir);
// console.log('    new appDir      : ' + rsf.appDir);
// console.log('    distDir         : ' + rsf.config.distDir);
// console.log('    files[0]        : ' + rsf.files[0]);

// ─── Step 5: Update next.config.ts ───────────────────────────────────────────

const nextConfigPath = path.join(ROOT, 'next.config.ts');
let nextConfig = fs.readFileSync(nextConfigPath, 'utf8');
if (!nextConfig.includes('distDir')) {
  nextConfig = nextConfig.replace(
    /const nextConfig: NextConfig = \{/,
    `const nextConfig: NextConfig = {\n  distDir: '${BUILD_DIR}',`
  );
  console.log('[+] Added distDir to next.config.ts');
} else {
  nextConfig = nextConfig.replace(/distDir: '[^']*'/, `distDir: '${BUILD_DIR}'`);
  console.log('[+] Updated distDir in next.config.ts');
}
fs.writeFileSync(nextConfigPath, nextConfig);

// ─── Step 6: Write vercel.json ───────────────────────────────────────────────

fs.writeFileSync(path.join(ROOT, 'vercel.json'), JSON.stringify({
  buildCommand: 'echo skip',
  outputDirectory: BUILD_DIR,
}, null, 2));
console.log('[+] Written vercel.json');

// ─── Step 7: Write .vercelignore ─────────────────────────────────────────────

fs.writeFileSync(path.join(ROOT, '.vercelignore'), [
  'node_modules',
  '.git',
  '.env.local',
  '.env*.local',
  '*.pem',
  'npm-debug.log*',
  '.DS_Store',
  'prepare-vercel.js',
  'prepare-deploy.js',
  'fix-*.js',
  'restore-*.js',
].join('\n') + '\n');
console.log('[+] Written .vercelignore');

// ─── Done ────────────────────────────────────────────────────────────────────

console.log('');
console.log('[DONE] Ready to deploy. Run:');
console.log('');
console.log('   vercel deploy --prod');
console.log('');
