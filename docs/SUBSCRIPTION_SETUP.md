# Turning on the Co-Pilot subscription

The app already supports a subscription mode: instead of the player's own Anthropic key, questions go to the Co-Pilot service, which checks their license key, enforces their plan's limits and forwards the question to Anthropic using your key. This guide sets that service up. It takes about an hour, and everything runs on free plans until you have real traffic.

You'll need three accounts: **Polar** (takes payments, handles sales tax, issues license keys), **Cloudflare** (runs the service) and **Anthropic** (the AI).

## 0. Lock your accounts down first

Whoever gets into one of these accounts gets your money or your users' trust, so do this before anything else:

1. Turn on **two-factor sign-in** (an authenticator app or a passkey, not SMS) on **GitHub, Polar, Cloudflare and Anthropic**, and on the email account they all send password resets to.
2. Give each one its own long password from a password manager.
3. On GitHub (repo → Settings):
   - **Rules → Rulesets**: add a rule for `main` that blocks force pushes and deletion.
   - **Releases**: turn on **immutable releases**, so a published installer can never be swapped out later.
   - **Actions → General**: set "Workflow permissions" to **read repository contents**, and set fork pull request workflows to **require approval for all outside collaborators**.
   - **Security**: turn on Dependabot alerts, secret scanning and push protection (free for public repos).

## 1. Anthropic: a key just for the service

1. At platform.claude.com, create a new **workspace** called "SC Co-Pilot service". Keeping it separate from your own key means its spending is easy to see and limit.
2. Create an API key in that workspace. Paste it straight into the Cloudflare prompt in step 3 and nowhere else: never into a file, the code, Discord or a screenshot. If it ever leaks, see "If something leaks" below.
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
4. Optional but recommended: create an **Organization Access Token** with only the `license_keys:write` scope and an expiry date (renew it yearly). With it, the service uses Polar's server-side check.
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
DAILY_BUDGET_USD = "25"
TRIAL_DAILY_USD = "3"
```

`DAILY_BUDGET_USD` pauses the whole service for the rest of the day (UTC) if total AI spend passes it. `TRIAL_DAILY_USD` does the same for free trials only, so nobody can farm trial keys. Raise the daily budget to about twice your normal daily spend as you grow.

Then create the database tables, add the secrets and deploy:

```
npm run db:init
npx wrangler secret put ANTHROPIC_API_KEY
npx wrangler secret put POLAR_TOKEN
npx wrangler secret put KEY_PEPPER
npm run deploy
```

For `KEY_PEPPER`, paste a long random string from your password manager's generator (40+ characters). It scrambles the license-key fingerprints in the database, so even a copy of the database can't be matched to real keys. Set it once before launch and never change it: changing it resets everyone's usage counts.

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

## If something leaks

- **Anthropic key:** in the Anthropic console, create a new key in the service workspace, run `npx wrangler secret put ANTHROPIC_API_KEY` with the new one, then delete the old key. Players notice nothing.
- **Polar token:** revoke it in Polar, make a new one, `npx wrangler secret put POLAR_TOKEN`.
- **A customer's license key** (shared publicly, resold): revoke it in Polar. It stops working within 10 minutes. The customer can be issued a new one.
- **GitHub account:** change the password, revoke sessions and tokens, check recent releases and commits. Immutable releases mean old installers can't have been swapped.

## Day to day

**See usage and cost per month:**

```
npx wrangler d1 execute sc-copilot --remote --command "SELECT period, COUNT(*) AS subscribers, SUM(replies) AS replies, SUM(web) AS web, ROUND(SUM(cost_micro)/1e6, 2) AS usd FROM usage WHERE period NOT LIKE 'd:%' GROUP BY period ORDER BY period DESC"
```

**Change a plan's limits** without touching code: set `TIERS_JSON` in `[vars]`, for example `TIERS_JSON = '{"pilot":{"replies":2500}}'`, then `npm run deploy`. The defaults live in `server/src/plans.js`.

**Price changes at Anthropic:** update `PRICES` in `server/src/plans.js` so the cost tracking stays accurate.

**Switching to Lemon Squeezy:** set `LICENSE_PROVIDER = "lemonsqueezy"` and `LS_STORE_ID`, and put variant IDs in `TIER_MAP` instead of benefit IDs. Lemon Squeezy's license check has a much lower rate limit than Polar's, so Polar is the better fit as you grow.

## How the service works

| File | What it does |
|---|---|
| `src/index.js` | Checks the key, applies the plan's limits, forwards the question to Anthropic and streams the answer back |
| `src/sanitize.js` | Rebuilds every request from scratch, keeping only what the app actually sends |
| `src/license.js` | Asks Polar (or Lemon Squeezy) whether a key is active and which plan it's for. Good results are cached for 10 minutes, bad keys for 2. If Polar is down, a key that worked in the last 2 hours keeps working |
| `src/meter.js` | Reads the token counts out of a copy of the streamed answer, so each reply's real cost is recorded even if the player hangs up |
| `src/store.js` | The database: license cache, monthly and daily usage, per-minute rate limit, PCs per key, one trial per PC |
| `src/plans.js` | Plans, limits and Anthropic's prices |
| `test/unit.mjs`, `test/run.mjs` | 14 unit checks, then 36 checks against a fake Anthropic and a fake Polar (`npm test`), including attack attempts |
| `test/app_e2e.py` | The app's real AI code against the service running locally |

Rules it enforces, per key:

- Monthly replies, web lookups and smart (Sonnet) replies, by plan. The trial is a one-time allowance.
- A daily cap, a per-minute cap, two questions in flight at once at most, and a monthly cost ceiling, so one runaway script can't run up a bill.
- One question counts once, however many tool round trips it takes. Every request also counts toward a hidden cap (3 per reply in the plan), so faking tool round trips can't dodge the limits. A follow-up only counts as part of the same question if it carries nothing but tool results for tool calls the service itself saw, each usable once.
- Web search is removed from the request when the month's lookups are used up, so the AI still answers without searching.
- Requests for other models are switched to the plan's model. Huge requests are refused. Before a question goes out, it reserves its worst-case cost, counting every web search pass (each one re-reads the whole prompt plus the results so far) and Haiku 5.5's 5x price above 100,000 tokens. The real cost replaces the reservation when the answer finishes.
- A key works on up to 3 PCs used in the last 30 days. Each PC can use one free trial, ever, with at most 3 new trials a day per home network.
- Usage is counted before the question goes to Anthropic, and the cost is read from a copy of the answer, so hanging up early doesn't make a question free.

Safety rules, for everyone:

- Only plain text, the app's own tools, web search and up to two inline screenshots (for screen checks, each reserved at 6,000 tokens) get through. Anthropic's paid extras (code execution, web fetch, MCP connectors, file uploads, priority tier, fast mode, beta features) are stripped, so a modified app can't bill them to you.
- Anthropic's account errors (for example "credit balance too low") are never shown to players.
- Unknown license keys are checked with Polar at most 10 times a minute per network, and at most 60 times a minute in total, so nobody can guess keys or flood Polar. Customers whose key already worked are never held back by these limits, and if Polar is down their key keeps working for 2 hours.
- Each network can make at most 120 requests a minute before anything touches the database (a normal player makes a handful), so one flooding machine can't knock the service over for everyone. Cloudflare's free plan has a daily request cap; move to the paid Workers plan before launch so a flood can't use it up.
- Keys and PC IDs are stored only as keyed fingerprints (HMAC-SHA-256 with `KEY_PEPPER`). If `KEY_PEPPER`, `ANTHROPIC_API_KEY`, `POLAR_ORG_ID` or `TIER_MAP` is missing, the service refuses every request instead of running half set up. Customer emails are stored masked (`m•••@gmail.com`). Questions and answers are never stored, and Cloudflare's per-request logs are turned off in `wrangler.toml`.
