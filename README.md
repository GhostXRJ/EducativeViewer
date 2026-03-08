# EducativeViewer

A Next.js application for viewing Educative.io course content.

---

## Prerequisites

- [Node.js](https://nodejs.org/) v18 or later
- [Vercel CLI](https://vercel.com/docs/cli) — for Vercel deployment only (`npm install -g vercel`)

---

## Environment Variables

Copy the example file and fill in your values:

```bash
cp .env.local.example .env.local
```

| Variable | Description |
|---|---|
| `PROXY_SECRET` | Secret shared with your Cloudflare Worker (`x-edu-proxy` header). Production only — not required locally |
| `BACKEND_API_BASE` | Base URL of the Cloudflare Worker proxying Flask API calls |
| `NEXT_PUBLIC_STATIC_FILES_BASE` | Base URL of the CDN / R2 bucket serving static assets |
| `REVALIDATE_SECRET` | Shared secret between Next.js and the Flask backend for cache revalidation |
| `VERCEL_ENV` | Set to `development` locally. Automatically set by Vercel in production |

---

## Running Locally

1. **Install dependencies**
   ```bash
   npm install
   ```

2. **Configure environment**
   ```bash
   cp .env.local.example .env.local
   # Edit .env.local and fill in your values
   ```

3. **Extract the build output**
   ```bash
   node prepare-deploy.js
   ```
   This extracts `.next.zip` into `nextBuild/` and patches the manifest files.

4. **Start the server**
   ```bash
   npx next start
   ```

   The app will be available at [http://localhost:3000](http://localhost:3000).

> **Note:** To run in dev mode (with hot reload) you need the source code (`app/` directory).
> `next start` serves the pre-built output from `nextBuild/` without requiring source files.

---

## Deploying to Vercel

### First-time setup

1. **Install Vercel CLI**
   ```bash
   npm install -g vercel
   ```

2. **Login to Vercel**
   ```bash
   vercel login
   ```

3. **Link to your Vercel project**
   ```bash
   vercel link
   ```

4. **Add environment variables** in your Vercel project dashboard:
   - Go to your project → **Settings → Environment Variables**
   - Add all variables from `.env.local.example` with production values
   - Do **not** set `VERCEL_ENV` — Vercel sets this automatically

### Every deployment

1. **Prepare the build output**
   ```bash
   node prepare-deploy.js
   ```

2. **Deploy to production**
   ```bash
   vercel deploy --prod
   ```

Your site will be live at your Vercel project URL (e.g. `https://edu-viewer.vercel.app`).

### What `prepare-deploy.js` does

- Extracts `.next.zip` → `nextBuild/` (Vercel auto-ignores `.next/`, so a rename is required)
- Patches `required-server-files.json` to replace build-machine paths with `/vercel/path0`
- Updates `next.config.ts` with `distDir: 'nextBuild'`
- Writes `vercel.json` with a no-op build command (skips rebuild on Vercel's servers)
- Writes `.vercelignore` to prevent unnecessary files from being uploaded

> `nextBuild/` is listed in `.gitignore` — it is always regenerated locally by `prepare-deploy.js` and never committed.
