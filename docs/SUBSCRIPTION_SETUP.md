# Turning on the Co-Pilot subscription

The app already supports a subscription mode: instead of the player's own Anthropic key, questions go to the Co-Pilot service, which checks their license key, enforces their plan's limits and forwards the question to Anthropic using your key. This guide sets that service up. It takes about an hour, and everything runs on free plans until you have real traffic.

You'll need three accounts: **Polar** (takes payments, handles sales tax, issues license keys), **Cloudflare** (runs the service) and **Anthropic** (the AI).

## 1. Anthropic: a key just for the service

1. At platform.claude.com, create a new **workspace** called "SC Co-Pilot service". Keeping it separate from your own key means its spending is easy to see and limit.
2. Create an API key in that workspace. Keep it somewhere safe. You'll paste it into Cloudflare in step 3.
3. Set a **monthly spend limit** on the workspace (start with $25). If something goes wrong, this caps the damage.
4. In the organization settings, make sure **web search** is enabled, or web lookups will fail for subscribers.

## 2. Polar: products and license keys

1. Sign up at polar.sh and create an organization. Copy its **Organization ID** (Settings → General).
2. Create the products below. Each one gets its own **License Key** benefit, and that benefit's ID is how the service knows which plan a key belongs to.

   | Product | Price | Benefits |
   |---|---|---|
   | SC Co-Pilot Pilot | $3.99 monthly, $35.99 yearly | License key ("Pilot key") |
   | SC Co-Pilot Captain | $7.99 monthly, $71.99 yearly | License key ("Captain key"), Discord role |
   | SC Co-Pilot Free Trial | Free, one time | License key ("Trial key") |

   License key settings: no expiry, no activation limit (the service limits each key to 3 PCs itself). For the subscriptions, the key is revoked automatically when the subscription ends.
3. Copy each license-key **benefit ID**.
4. Optional but recommended: create an **Organization Access Token** with the `license_keys:write` scope. With it, the service uses Polar's server-side check.
5. Copy your **customer portal** link (where subscribers manage or cancel) and a **checkout link** for the products page.

## 3. Cloudflare: deploy the service

You need Node.js 22 or newer on your PC.

```
cd server
npm install
npx wrangler login
npx wrangler d1 create sc-copilot
```

`d1 create` prints a `database_id`. Paste it into `server/wrangler.toml`, then fill in the `[vars]` section:

```toml
[vars]
LICENSE_PROVIDER = "polar"
POLAR_ORG_ID = "your organization ID"
TIER_MAP = '{"pilot benefit id":"pilot","captain benefit id":"captain","trial benefit id":"trial"}'
MANAGE_URL = "your Polar customer portal link"
UPGRADE_URL = "your checkout link"
```

Then create the database tables, add the secrets and deploy:

```
npm run db:init
npx wrangler secret put ANTHROPIC_API_KEY
npx wrangler secret put POLAR_TOKEN
npm run deploy
```

`deploy` prints the service address, something like `https://sc-copilot-service.yourname.workers.dev`. Check it's alive by opening `/health` on that address in a browser. It should say `{"ok":true,...}`.

## 4. Point the app at it

In `App/sc_version.py`, set:

```python
SERVICE_URL = "https://sc-copilot-service.yourname.workers.dev"
STORE_URL = "your checkout link"
```

Commit, tag a release, and the "Co-Pilot subscription" option in the app switches from "coming soon" to live.

## 5. Test it end to end

1. Buy the Free Trial in Polar yourself. You'll get a trial key by email.
2. In the app: Settings → AI mode → Co-Pilot subscription, paste the key, press Save. "Your plan" should show "Free trial · 0 of 100 trial replies used".
3. Ask it something in game. The count goes up.

## Day to day

**See usage and cost per month:**

```
npx wrangler d1 execute sc-copilot --remote --command "SELECT period, COUNT(*) AS subscribers, SUM(replies) AS replies, SUM(web) AS web, ROUND(SUM(cost_micro)/1e6, 2) AS usd FROM usage WHERE period NOT LIKE 'd:%' GROUP BY period ORDER BY period DESC"
```

**Change a plan's limits** without touching code: set `TIERS_JSON` in `[vars]`, for example `TIERS_JSON = '{"pilot":{"replies":2500}}'`, then `npm run deploy`. The defaults live in `server/src/plans.js`.

**Price changes at Anthropic:** update `PRICES` in `server/src/plans.js` so the cost tracking stays accurate.

**Switching to Lemon Squeezy:** set `LICENSE_PROVIDER = "lemonsqueezy"` and `LS_STORE_ID`, and put variant IDs in `TIER_MAP` instead of benefit IDs.

## How the service works

| File | What it does |
|---|---|
| `src/index.js` | Checks the key, applies the plan's limits, forwards the question to Anthropic and streams the answer back |
| `src/license.js` | Asks Polar (or Lemon Squeezy) whether a key is active and which plan it's for. Results are cached for 10 minutes |
| `src/meter.js` | Reads the token counts out of the streamed answer, so each reply's real cost is recorded |
| `src/store.js` | The database: license cache, monthly and daily usage, per-minute rate limit, PCs per key |
| `src/plans.js` | Plans, limits and Anthropic's prices |
| `test/run.mjs` | 14 checks against a fake Anthropic and a fake Polar (`npm test`) |
| `test/app_e2e.py` | The app's real AI code against the service running locally |

Rules it enforces, per key:

- Monthly replies, web lookups and smart (Sonnet) replies, by plan. The trial is a one-time allowance.
- A daily cap, a per-minute cap and a monthly cost ceiling, so one runaway script can't run up a bill.
- One question counts once, however many tool round trips it takes.
- Web search is removed from the request when the month's lookups are used up, so the AI still answers without searching.
- Requests for other models are switched to the plan's model. Huge requests are refused, which keeps every request under Haiku 5.5's 100,000-token price step.
- A key works on up to 3 PCs used in the last 30 days.
- Keys are stored only as SHA-256 hashes. Questions and answers are never stored.
