# Changelog

## 1.0.0

First public release.

- Instant voice commands for flight, power, shields, weapons, targeting, countermeasures, landing, doors, lights and more, matched on your PC with no AI delay.
- Voice macros: "prep for takeoff", "combat ready", "go dark", "evasive", "landing prep", plus your own.
- Optional AI co-pilot: answers questions about your session, places, ships, items, refinery yields and trade, using your own Anthropic API key. Subscription option coming soon.
- Spoken callouts for zones, quantum travel, combat, contracts, party and aUEC.
- Dashboard: Overview, Contracts, Combat and 30-day History from the game log.
- Live trade and mining prices from UEX.
- Click-through in-game overlay that follows the game's monitor, with a one-click NVIDIA driver fix.
- Reads your own keybinds and can give spare keys to actions Star Citizen leaves unbound, without touching your own binds. Detects and repairs key clashes.
- Personalities: six original co-pilot characters, plus a line editor to rewrite any callout or reply, with random variants and shareable line packs.
- Target reader (beta): reads your target's shield and hull off the HUD from boxes you draw once, answers "target status" / "are his shields down?", and can call out when shields drop.
- Community line-pack gallery: browse, preview and install packs in the app; share yours through a GitHub form.
- Subscription service ready to deploy (see docs/SUBSCRIPTION_SETUP.md): plans with monthly reply, web lookup and smart-reply allowances, a free trial, usage shown in Settings, and clear messages when an allowance runs out.
- Cheaper AI requests: the instructions and conversation are cached between questions.
- Ask what ships you can buy: by system, type (fighter, heavy fighter, cargo, mining...), dealer or budget, with the dealer and price. "Ship dealers in Stanton" works too.
- The AI stays in character as your ship's AI: answers first, in a sentence or two, with no disclaimers or talk about where it got the information.
- Knows the ship's state (gear, NAV/SCM, power, lights, doors and more) from its own commands and your own key presses, so it doesn't undo things by repeating them. Forgets when you change ships.
- Quantum fixed for Star Citizen 4.10: "quantum mode" switches to NAV, "engage quantum" switches to NAV if needed and holds the engage button, and it tells you when no destination is set.
- AI avatar on the overlay: a glowing core in a cloud of points that reacts when you talk, while it thinks, and to the loudness of its voice.
- Two new voice effects, Deep and dark and Echo chamber, plus a Pitch slider that makes any voice deeper or lighter.
- Security: your API key and subscription key are saved encrypted, locked to your Windows account. Updates only install if the file exactly matches the one published on GitHub. Line packs can only change lines, never settings. Pasted keys are cleaned of stray spaces and line breaks, and an Anthropic key pasted into the subscription box is caught instead of sent.
- Security (subscription service): requests are rebuilt from scratch so only what the app sends gets through, every request reserves its worst-case cost first, two questions in flight per key at most, usage is counted even if a request is cut off, one free trial per PC, daily spending brakes, throttled key guessing and floods, and no raw keys, PC IDs, full emails or request logs stored.
- New logo, shown on the taskbar, window, desktop shortcut, installer and website.
- First-run setup, automatic updates, Copy diagnostics for bug reports.
- 324 automated app tests and 48 service checks, including attack attempts, run on every change.
