VERSION = "1.0.0"
GITHUB_REPO = "mattboy112/SC-CoPilot"
HOMEPAGE = f"https://github.com/{GITHUB_REPO}"
ISSUES_URL = f"{HOMEPAGE}/issues/new"
RELEASES_URL = f"{HOMEPAGE}/releases/latest"
SITE_URL = "https://mattboy112.github.io/SC-CoPilot/"
PACKS_RAW = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/"
PACKS_INDEX_URL = PACKS_RAW + "packs/index.json"
PACKS_PAGE = f"{HOMEPAGE}/tree/main/packs"
SHARE_PACK_URL = f"{HOMEPAGE}/issues/new?template=line-pack.yml"

# The Co-Pilot subscription server (a proxy that holds the Claude key and checks subscriptions).
# Empty until it's launched; the app then shows the subscription option as "coming soon".
SERVICE_URL = ""
STORE_URL = ""

DISCLAIMER = ("SC Co-Pilot is an unofficial fan-made tool. It is not affiliated with, endorsed by or sponsored by "
              "Cloud Imperium Games or Roberts Space Industries. Star Citizen®, Squadron 42®, Roberts Space Industries® and "
              "Cloud Imperium® are trademarks of Cloud Imperium Rights LLC.")
