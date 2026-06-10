# Spec: Block J — Production Deploy & Hardening

## Overview
Containerize, deploy, secure, and add CI. Make Phase 2 production-ready.

## Tasks
1. Dockerfile (backend) + docker-compose for local parity
2. Deploy backend to Railway or Fly.io
3. Deploy frontend to Vercel; fill vercel.json proxy + Calendly placeholders
4. Real secrets management (Railway/Fly secrets, not .env in repo)
5. ROTATE any exposed keys immediately (Anthropic, OpenAI, Google, SendGrid)
6. Celery: move off worker_pool="solo" to prefork for real concurrency
7. GitHub Actions CI: ruff + mypy + pytest on every push/PR
8. Qdrant: move to Qdrant Cloud (managed)
9. Postgres: managed instance with automated backups

## GitHub Actions (.github/workflows/ci.yml)
- Trigger: push + pull_request
- Steps: checkout → setup python 3.11 → pip install →
         ruff check → mypy → pytest
- Block merge if any step fails

## Secrets Rotation (DO IMMEDIATELY)
- Revoke + regenerate every key that was ever in .env or committed
- Store new keys ONLY in the platform secret manager
- Confirm .env is gitignored and never in history (use git-filter-repo if so)

## Acceptance Criteria
- [x] Dockerfile builds and runs the backend
- [ ] Backend deployed; production /health returns 200       ← run: fly deploy / railway up
- [x] Frontend on Vercel; vercel.json proxy + Calendly filled (update Calendly username)
- [ ] All secrets in platform manager — none in repo or history  ← fly secrets set / railway vars
- [ ] Exposed keys ROTATED and old ones revoked             ← manual: each provider dashboard
- [x] Celery on prefork pool, concurrency > 1
- [x] GitHub Actions CI: ruff + mypy + pytest on every push
- [ ] Failing CI blocks merge  ← manual: GitHub Settings → branch protection → require CI
- [ ] Qdrant + Postgres on managed/cloud instances with backups  ← sign up for Qdrant Cloud + managed Postgres
