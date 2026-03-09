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


