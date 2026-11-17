# SC Co-Pilot

**A voice co-pilot and live dashboard for Star Citizen.**

Hold push-to-talk and say "gear down", "combat ready" or "target the biggest threat", and it presses your own keybinds. Ask "where do I sell Laranite near me?" or "what's my objective?" and it answers out loud using your real game data and live community prices. It calls out armistice zones, jurisdiction changes, kills, contracts and party joins. A small overlay in game shows your zone, objective and the last callout.

> Unofficial fan-made tool. Not affiliated with, endorsed by or sponsored by Cloud Imperium Games or Roberts Space Industries.

## Download

**[Get the latest installer →](https://github.com/mattboy112/SC-CoPilot/releases/latest)** · [Website](https://mattboy112.github.io/SC-CoPilot/)

1. Download `SC_CoPilot_Setup_x.y.z.exe` and run it. It installs just for you and doesn't need admin.
2. Windows may show "Windows protected your PC", because the installer isn't code-signed yet. Click **More info → Run anyway**.
3. The first time it opens, a two-minute setup walks you through your game folder, push-to-talk, the AI and the voice.

It checks for updates by itself and installs them in one click (Settings → About).

**Needs:** Windows 10 or 11 (64-bit), Star Citizen, and a microphone. Any graphics card works. The overlay's one-click driver fix is for NVIDIA cards.

## What it does

- **Instant voice commands, free and offline.** Speech recognition runs on your PC. Simple commands are matched on your PC too, so they fire right away with no AI delay. Say it however you like: "drop the gear", "guns hot", "kill the lights", "pop flares", "all power to shields", "next hostile", "who's shooting me".
- **Voice macros.** One phrase runs a sequence of keys: "prep for takeoff", "combat ready", "go dark", "evasive", "landing prep". Make your own on the Macros tab.
- **An AI co-pilot (optional).** Answers questions about your session ("how many kills this week?", "what did I spend today?"), finds places ("where can I refuel near me?", "does Checkmate have a refinery?"), finds ships and gear for sale, plans trade routes, and handles anything that isn't an instant command.
- **Callouts.** Spoken alerts for armistice, ungoverned space, monitored space, quantum arrival, kills, losses, CrimeStat, contracts, party and aUEC transfers.
- **Dashboard.** Overview, Contracts, Combat and a 30-day History, all read from the game's log file.
- **Trade & mining prices.** Live player-reported prices from [UEX](https://uexcorp.space/), with best sell/buy spots and routes.
- **In-game overlay.** A click-through panel with your zone, current objective, quantum status and the last thing the co-pilot said.
- **Personalities.** Pick how your co-pilot talks: Ship AI, Fleet officer, Laid-back hauler, Deadpan AI, Corporate assistant or Pyro outlaw. You can rewrite any callout or reply and give lines several versions to pick from at random.
- **Community line packs.** Install packs other players made from Personality → Browse community packs, or [share your own](packs/README.md).
- **Target reader (beta).** Ask "are his shields down?", "how's his hull?" or "target status". You draw a box around your target's shield and hull displays once, and it reads them off your screen. It can also call out when the target's shields drop.
- **Your keybinds, untouched.** It reads your own binds, so it presses what you've set. It can also give spare keys to the actions Star Citizen leaves unbound, like separate gear up and gear down, but only when you ask. It backs up your bindings file first.

## The AI: your choice

The AI is optional. Everything above except answering questions works without it.

| Mode | How it works |
|---|---|
| **Your own Anthropic API key** | Make a key at [platform.claude.com](https://platform.claude.com/) and add a few dollars of credit. You pay Anthropic directly, roughly a tenth of a cent per question with the default model. |
| **Co-Pilot subscription** | *Coming soon.* A monthly plan, no key or Anthropic account needed. |
| **Off** | Instant commands, macros, callouts, dashboard, trade and overlay all still work. |

## Voices

- **Microsoft voices** (default): natural sounding, free, need internet.
- **Windows voices**: built in, instant, offline, more robotic.
- **Kokoro**: very natural and fully offline. Available when you run from source. It isn't in the installer yet.

Every voice can run through an effect: cockpit AI, ship computer, helmet comms, long-range radio, deep and dark, or echo chamber. A Pitch slider makes any voice deeper or lighter.

## Tips

- **Overlay vanishes when you click into the game?** Set Star Citizen to **Borderless** (Graphics → Window Mode). On NVIDIA, open Settings → In-game overlay. It checks your driver's "Vulkan/OpenGL present method" for Star Citizen and can fix it in one click. Restart the game afterwards.
- **A command does nothing?** The Controls tab shows the key for every action, with a Test button. Some actions, like separate gear up and down or lights on and off, have no key by default. The Controls tab can assign spare ones. Close the game first, because it rewrites your bindings when it quits.
- **Star Citizen runs as administrator?** Then Windows blocks key presses from normal apps. Use Settings → Restart as administrator.
- **It mishears you?** Try Settings → Speech model → Small, and check the right microphone is picked.
- **Found a bug?** Settings → About → **Copy diagnostics**, then [open an issue](https://github.com/mattboy112/SC-CoPilot/issues/new) and paste them in.

## What it can and can't see

Star Citizen has no official data feed. Most of what it knows comes from `Game.log`, the file the game writes for its own debugging. That covers your ship, zones, quantum travel, contracts and objectives, ship kills and losses, deaths, purchases, party and aUEC transfers. The log has no shields, hull, fuel, ammo, wallet balance or on-foot kills. The one exception is your *target's* shields and hull, which the optional target reader gets by looking at the boxes you drew on your HUD. What gets logged can change between patches.

## Fair play and privacy

It only reads files the game leaves on disk and presses keys the way your keyboard does, when you ask. It never reads or modifies game memory, injects anything, or plays for you. Your microphone is only recorded while you hold push-to-talk, and speech recognition runs on your PC. See [PRIVACY.md](App/legal/PRIVACY.md) for exactly what leaves your PC and when.

## Building from source

See [docs/DEVELOPING.md](docs/DEVELOPING.md).

## License

Free to use and share for non-commercial purposes under the [PolyForm Noncommercial License 1.0.0](LICENSE). Credits for the open-source parts it's built on are in [THIRD_PARTY_NOTICES.md](App/legal/THIRD_PARTY_NOTICES.md).

Star Citizen®, Squadron 42®, Roberts Space Industries® and Cloud Imperium® are trademarks of Cloud Imperium Rights LLC.
