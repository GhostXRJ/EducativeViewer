# EducativeViewer

A Next.js application for viewing Educative.io course content.

---

## Prerequisites

- [Node.js](https://nodejs.org/) v18 or later
- [GitHub CLI](https://cli.github.com/) (`gh`) — for downloading releases and managing deployments
- [Vercel CLI](https://vercel.com/docs/cli) — installed automatically by `deploy.js` if missing

---

## Quick Start

Everything is managed through the interactive deploy script:

```bash
node deploy.js
```

This opens a menu that handles local dev, Vercel deployment, GitHub releases, environment variables, and more.

---

## deploy.js — Menu Overview

| Option | Description |
|---|---|
| `1` | Download zip from GitHub Releases + push env vars + deploy to Vercel |
| `2` | Download zip from GitHub Releases + run locally |
| `3` | Push env vars + deploy to Vercel (uses existing `.next.zip`) |
| `4` | Run locally (uses existing `.next.zip`) |
| `5` | Push `.env.local` variables to Vercel only |
| `6` | Create a new GitHub Release with `.next.zip` |
| `7` | Upload `.next.zip` to an existing GitHub release |
| `8` | Manage GitHub repo / tags (change repo, add remotes, create/push/delete tags) |
| `9` | Manage Vercel (link project, list/add/remove env vars, list deployments) |
| `0` | Exit |

### Direct commands (non-interactive)

```bash
node deploy.js local          # download zip → prepare → next start
node deploy.js vercel         # download zip → push env vars → vercel deploy --prod
node deploy.js env            # push .env.local vars to Vercel only
node deploy.js release v1.0.0 # create a new GitHub release with .next.zip
node deploy.js upload v1.0.0  # upload .next.zip to an existing release
node deploy.js repo           # open GitHub repo / tags manager
node deploy.js vercel-manage  # open Vercel manager
```

---

## Environment Variables

Copy the example file and fill in your values:

```bash
cp .env.local.example .env.local
```

| Variable | Description |
|---|---|
| `PROXY_SECRET` | Secret shared with your Cloudflare Worker (`x-edu-proxy` header). Production only |
| `BACKEND_API_BASE` | Base URL of the Cloudflare Worker proxying Flask API calls |
| `NEXT_PUBLIC_STATIC_FILES_BASE` | Base URL of the CDN / R2 bucket serving static assets |
| `REVALIDATE_SECRET` | Shared secret between Next.js and the Flask backend for cache revalidation |
| `VERCEL_ENV` | Set to `development` locally. **Do not set in Vercel** — it's automatic |

Use `deploy.js` option **5** or **9 → c** to push these to Vercel automatically.

---

## Cloudflare Worker — Unified Proxy

The `cloudflare-worker.js` acts as a single public entry point for the app, sitting in front of both Vercel and your static file server.

### Why it is needed

Vercel deployments serve everything under the `vercel.app` domain.  
When a page rendered by Vercel needs a static asset (image, JS chunk, etc.) that lives on a different origin (e.g. an R2 bucket or a self-hosted CDN), the browser may encounter cross-origin issues or the asset URL may be hard to keep consistent across environments.

By routing **all traffic through one Cloudflare Worker domain** you get:

- A consistent domain for every resource — pages, API calls, and static assets.
- Optional Basic Auth applied uniformly at the edge.
- The ability to move the static server or the Vercel project without touching client-side URLs.

### How it works

```
Browser → Cloudflare Worker
              │
              ├─ pathname starts with /api  →  static file server (staticBase)
              │
              └─ everything else            →  Vercel (vercelBase)
```

Every upstream request gets the `x-edu-proxy` header injected so Vercel can verify the request came through the worker.

### Setup

1. Open `cloudflare-worker.js` and fill in the `config` block at the top:

   | Field | Description |
   |---|---|
   | `vercelBase` | Your Vercel deployment URL, e.g. `https://my-app.vercel.app` |
   | `staticBase` | Base URL of the server that hosts your static files (R2, S3, nginx, …) |
   | `staticPrefix` | URL path prefix routed to `staticBase` (default `/api`) |
   | `proxySecret` | A random secret shared with Vercel via the `PROXY_SECRET` env var |
   | `siteName` | Label shown in Basic Auth dialog |
   | `user` / `pass` | Basic Auth credentials (set both to `""` to disable) |
   | `publicPaths` | Array of path prefixes that bypass Basic Auth (e.g. `["/webhook"]`) |

2. Deploy the worker to Cloudflare:
   - Go to **Cloudflare Dashboard → Workers & Pages → Create Worker**.
   - Paste the contents of `cloudflare-worker.js` into the editor and save.
   - Assign a custom domain (or use the `*.workers.dev` subdomain).

3. Set `PROXY_SECRET` in your Vercel project environment variables to the same value as `config.proxySecret` in the worker. Your Vercel app can then reject any request that doesn't carry the correct header.

4. Point `NEXT_PUBLIC_STATIC_FILES_BASE` (and any other asset base URLs) to the **worker domain** rather than to Vercel or the static server directly.

---

## One-time GitHub Actions Setup

The workflow in [.github/workflows/deploy.yml](.github/workflows/deploy.yml) deploys to Vercel when triggered **manually** from the Actions tab.

Add these in your GitHub repo → **Settings → Secrets and variables → Actions**:

**Secrets:**

| Name | Where to get it |
|---|---|
| `VERCEL_TOKEN` | [vercel.com/account/tokens](https://vercel.com/account/tokens) |
| `GH_PAT` | GitHub → Settings → Developer settings → Personal access tokens (needs `repo` scope) |

**Variables:**

| Name | Where to get it |
|---|---|
| `VERCEL_ORG_ID` | Run `vercel link` → `.vercel/project.json` → `orgId` |
| `VERCEL_PROJECT_ID` | Same file → `projectId` |

To trigger a deployment: **GitHub → Actions → "Deploy to Vercel" → Run workflow → enter the release tag**.


