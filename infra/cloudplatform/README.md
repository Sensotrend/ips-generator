# Deploying to cloudplatform.fi (Virtuozzo)

Development environment only: synthetic data, `EXTRACTOR=replay` (no LLM), `APP_ENV=development`
(fixed dev reviewer, no login), no access control. Do not put real patient data here.

## How it works

1. GitHub Actions (`.github/workflows/deploy.yml`) builds three images and pushes them to GHCR, tagged
   with the commit SHA and `dev`: `ips-generator-backend` (api and worker), `ips-generator-web` (PWA +
   NGINX proxying `/api/`) and `ips-generator-matchbox` (Matchbox with our IG config baked in).
2. The `deploy` job calls the Virtuozzo API (`redeploy.sh`) to redeploy the `api`, `worker` and `web`
   node groups to the new tag. The api runs the Alembic migrations when it starts.
3. Postgres, Redis, MinIO and Matchbox are created once by `manifest.jps` and are not redeployed.

To deploy: push to `main`, or `gh workflow run deploy.yml -f ref=<branch>`. Deploys are serialised
(one shared environment).

## One-time setup

1. **GHCR images.** Run the workflow once (the first run only builds; the deploy step fails until the
   environment exists). In GitHub, the packages are private (the repo is private); the manifest asks for a GitHub user and a read:packages token.
2. **Environment.** In the cloudplatform.fi dashboard choose *Import* and paste `manifest.jps`; fill in the
   form (the real owner/repo, passwords). Matchbox needs about 15 minutes on first start to install the IG.
3. **API token.** In the dashboard create an access token (Settings, Access Tokens) with API access.
4. **GitHub.** Create the Environment `dev` with the secrets `JELASTIC_API_URL` (the platform's API host,
   `https://app.<region domain>`) and `JELASTIC_TOKEN`, and the variable `JELASTIC_ENV_NAME`.
5. Custom domain: point an A record at the public IP of the `bl` (NGINX load balancer) node, bind the domain
   to the environment (Settings → Custom Domains), then install the Let's Encrypt add-on on `bl`. The balancer
   must forward to the `web` node on port 80; if it does not pick it up automatically, add an upstream to
   `/etc/nginx/conf.d/` on `bl`.

## Unverified: check these on the platform

`manifest.jps` and `redeploy.sh` are written from the Virtuozzo documentation, not tested here.

- API host and the exact method name/parameters of `RedeployContainersByGroup`.
- Whether `${nodes.<group>.master.intIP}` stays stable after a redeploy (the NGINX upstream and the
  env vars of api/worker use these IPs). If not, switch to the nodes' internal hostnames.
- Whether the NGINX balancer (`bl`) picks up the Docker `web` node automatically (otherwise set the upstream by hand).
  balancer with the environment domain may be cheaper).
- Postgres 18 and the MinIO image running as Docker nodes with volumes at the paths given.
- Cloudlet sizes (1 cloudlet = 128 MiB RAM): Matchbox gets up to 4 GB.
- MinIO bucket: the manifest creates it by making `/data/ips-documents`.
