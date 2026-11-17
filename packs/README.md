# Community line packs

Line packs change what SC Co-Pilot says: callouts, replies to commands and greetings. Anyone can install them from the app (**Personality → Browse community packs**), and anyone can share their own.

## Share your pack

1. In SC Co-Pilot, edit lines on the **Personality** tab until you like them.
2. Click **Export my lines…** and save the file.
3. [Open a "Share a line pack" issue](https://github.com/mattboy112/SC-CoPilot/issues/new?template=line-pack.yml), give it a name and description, and paste the whole file.
4. Once it's approved, a bot adds it to the gallery and replies on your issue.

## Rules

Packs are checked by a person before they go up. To get approved:

- Write your own lines. No quotes or catchphrases from movies, TV, games or other people's work.
- Don't impersonate real people, voice actors or streamers.
- Keep it PG-13: no slurs, hate, harassment or sexual content.
- No links or advertising.
- Use the placeholders a line supports (shown in the app under each line's name, like `{victim}` or `{n}`).

## For maintainers

- Approve a pack by adding the `pack-approved` label to its issue. The **Add line pack** workflow checks it, adds `packs/<name>.json`, updates `packs/index.json`, comments and closes the issue.
- To add or fix one by hand: edit the file, then run `python packaging/packs.py build-index` and `python packaging/packs.py check`.
