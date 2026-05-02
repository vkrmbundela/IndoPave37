# MEP-Opt Frontend Dashboard

React + Vite frontend for the MEP-Opt pavement analysis and optimization workflow.

## Prerequisites

- Node.js 20+
- Backend API running from `mep_opt/web/main.py` (FastAPI)

## Install

```bash
npm install
```

## Run in Development

```bash
npm run dev
```

By default, the dashboard posts API calls to:

- `http://127.0.0.1:8000/api/solve`
- `http://127.0.0.1:8000/api/optimize`

## Configure API Base URL

Create `.env.local` in this folder if your backend uses a different host/port.

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

For GitHub Pages production builds, you can also set:

```env
VITE_BASE_PATH=/your-repo-name/
```

## Validation

```bash
npm run lint
npm run build
```

## Deploy Frontend to GitHub Pages

This repository includes a GitHub Actions workflow at `.github/workflows/deploy-frontend-pages.yml`.

1. Push your code to GitHub (branch `main`).
2. In GitHub repository settings, enable Pages with source: GitHub Actions.
3. Add repository variable:
	- `VITE_API_BASE_URL=https://<your-hf-space>.hf.space`
4. Push a commit touching `frontend/` (or run the workflow manually).

After deployment, your public frontend URL will be:

- `https://<your-github-username>.github.io/<your-repo-name>/`
