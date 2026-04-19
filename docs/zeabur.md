# Zeabur Deployment

## Deployment Model

Recommended Zeabur services from the same GitHub repository:

1. `web`
2. `worker`
3. PostgreSQL service in the future, or SQLite for first local stage only

## Official Zeabur Notes

Based on Zeabur official Dockerfile docs:

- Zeabur auto-detects a root `Dockerfile` and deploys with Docker
- You can also deploy a named Dockerfile as `[service-name].Dockerfile` or `Dockerfile.[service-name]`
- Docker Compose is not supported directly on Zeabur

Sources:

- [Deploying with Dockerfile](https://zeabur.com/docs/en-US/deploy/dockerfile)
- [Deployment Methods](https://zeabur.com/docs/en-US/deploy/methods)
- [Deploy Python Projects](https://zeabur.com/docs/en-US/guides/python)

## Files in This Repo

- `Dockerfile`
  - for the `web` service
- `worker.Dockerfile`
  - for the `worker` service when the service name is `worker`

## Environment Variables

Required:

- `DATABASE_URL`
- `APP_ENV`
- `DISCORD_WEBHOOK_URL`
- `DISCORD_ENABLED`
- `DISCORD_TIMEOUT_SECONDS`
- `DISCORD_RETRY_ATTEMPTS`
- `DISCORD_RETRY_BACKOFF_SECONDS`
- `DISCORD_DAILY_REPORT_TOP_N`
- `ENABLE_SCHEDULER`
- `SCHEDULER_TIMEZONE`
- `SCREENING_HOUR`
- `SCREENING_MINUTE`
- `SCREENING_WEEKDAYS`
- `SCREENING_TOP_N`
- `MIN_PRICE_BARS_FOR_SCREENING`
- `FEATURE_COST_GUARDRAILS_ENABLED`
- `FEATURE_CANDIDATE_AI_ANALYSIS_ENABLED`
- `FEATURE_HOLDING_AI_ANALYSIS_ENABLED`
- `FEATURE_DISCORD_NOTIFICATIONS_ENABLED`
- `OVERALL_MONTHLY_BUDGET_TWD`
- `AI_MONTHLY_BUDGET_TWD`

Recommended for Zeabur:

- `PORT`
- `APP_ENV=production`
- `ENABLE_SCHEDULER=false` on `web`
- `ENABLE_SCHEDULER=true` on `worker`
- keep secrets in Zeabur env vars instead of committing them into repo state
- mount shared PostgreSQL rather than relying on SQLite in production

## Service Setup

### Web

- create a service from the GitHub repo
- let Zeabur use root `Dockerfile`
- expose HTTP traffic on `PORT`

### Worker

- create another service from the same repo
- set service name to `worker`, or configure service to use `worker.Dockerfile`
- no public port required
- keep `ENABLE_SCHEDULER=true`
- restart worker after changing scheduler settings in the UI if you want cron timing to take effect immediately

## SQLite vs PostgreSQL

SQLite is suitable for local bootstrap.
For Zeabur production deployment, PostgreSQL is recommended so that `web` and `worker` share one database safely.

## Logs

- runtime logs are written to `data/logs/`
- on Zeabur, prefer reading container logs from the platform, and use file logs as an application-side fallback
