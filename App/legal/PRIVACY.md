# Privacy

SC Co-Pilot runs on your PC. It has no account system, no analytics and no tracking. Your settings, logs and voice files stay in your Windows user folder (`%APPDATA%\SC Co-Pilot` and `%LOCALAPPDATA%\SC Co-Pilot`).

## What it reads on your PC

- Star Citizen's `Game.log` and log backups, for the dashboard, history and callouts.
- Your keybinds file (`actionmaps.xml`) and the game's default keybinds inside `Data.p4k`, so it can press the right keys.
- Your microphone: **only while you hold push-to-talk**, or all the time if you turn on voice activation. Either way, speech recognition runs on your PC and audio is never uploaded or saved. With voice activation, anything you say that doesn't start with the co-pilot's name is thrown away (unless you turn that check off).
- Notes you ask it to remember and your timers are saved in your settings folder on your PC.
- If you set up the target reader: the small screen areas you drew boxes around, a few times a second at most. The pixels are analysed on your PC and never saved or sent.

## What leaves your PC, and only when you use the feature

| When | Sent to | What |
|---|---|---|
| You ask the AI something (own-key mode) | Anthropic (Claude API) | Your question as text, plus a short summary of your current game session (location, contracts, recent events) so it can answer. Sent with your API key under [Anthropic's terms](https://www.anthropic.com/legal). |
| You ask the AI something (subscription mode) | The Co-Pilot service, which forwards it to Anthropic | The same as above, plus your subscription key so the service can check your plan, and an anonymous ID for your PC (so one subscription works on up to 3 PCs). The service stores keys and PC IDs only as one-way scrambled fingerprints, your email only in masked form (like m•••@gmail.com), and usage counts (replies, web lookups, tokens) per key. It doesn't store your questions or answers. |
| The AI looks at your screen (screen checks on) | Anthropic, directly or through the Co-Pilot service | A screenshot of the Star Citizen window, shrunk and with the co-pilot's own overlay blacked out. Taken only after pre-flight or when the AI decides it needs to look, and only while the game is in front. Anything showing on top of the game, like a Discord overlay or a Windows notification, can be in the picture. Never saved on your PC or by the service. Turn it off under Settings → Screen checks. |
| The AI uses web search | Anthropic's web search | The search terms it picked. |
| You look up prices, ships, items or places | UEX Corp API | The commodity, ship or place you asked about. |
| You use a Microsoft voice | Microsoft's text-to-speech service | The text being spoken. |
| First use of speech recognition or Kokoro voices | Hugging Face / GitHub | A normal file download. |
| Update check (if on) | GitHub | A request for the latest version number. |
| You browse community line packs | GitHub | A download of the pack list and the packs you preview or install. |

Nothing is sent to the developer, except when you use the Co-Pilot subscription as described above, or choose to paste the "Copy diagnostics" text into a bug report. Diagnostics never include your API or subscription key.

On your PC, your API key and subscription key are saved encrypted with Windows' built-in data protection, so they only unlock for your Windows account on this PC. Anyone who copies the settings file elsewhere gets nothing usable.

## Deleting your data

Uninstall SC Co-Pilot, then delete the two `SC Co-Pilot` folders in `%APPDATA%` and `%LOCALAPPDATA%`.
