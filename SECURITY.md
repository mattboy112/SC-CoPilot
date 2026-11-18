# Security

## Reporting a problem

Please don't open a public issue for a security problem. Use **Report a vulnerability** on this repository's Security tab instead, so only the maintainer sees it. You'll get a reply within a few days.

## What's protected

**On your PC**
- Your Anthropic API key and Co-Pilot license key are saved encrypted with Windows' built-in data protection. They only unlock for your Windows account on that PC.
- Keys never appear in logs, in "Copy diagnostics" or in error messages.
- Updates only install if the file exactly matches the checksum GitHub publishes for SC Co-Pilot's own release.
- Line packs can only change spoken lines, never settings or files.
- The AI can only press known Star Citizen controls and read game data. It can't open websites, write files or run programs.

**The Co-Pilot subscription service**
- Requests are rebuilt from scratch, so only plain text, the app's own tools and web search reach Anthropic.
- Every request reserves its worst-case cost before it goes out, each key can have two questions in flight at most, and there are monthly, daily and per-minute limits plus a daily spending brake for the whole service.
- License keys and PC IDs are stored only as keyed fingerprints, emails only in masked form. Questions and answers are never stored.

## Known limits

- Installers aren't code-signed yet, so the updater trusts GitHub's checksum. Someone who took over the maintainer's GitHub account could publish a bad release.
- SC Co-Pilot installs for your user only. If you use "Restart as administrator", other software already running as you could tamper with the app's files first, as with any per-user app.
