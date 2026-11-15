# Chat and the browser page

## Chat

```bash
pip install -e ".[chat,local]"   # Claude's SDK, and the model that runs on your Mac
taxtrace ui                      # opens http://taxtrace.localhost:8766/
```

The page lists your workspace by folder and has a chat for tax rules, forms and what a document is for.
It answers with the first model in `--models` (default `claude,agy,local`) that can, and moves on to the
next when one can't (no key, quota used up, not installed):

- `claude`: Anthropic's API, with `ANTHROPIC_API_KEY` or a Keychain item holding the key (`--keychain`,
  default `anthropic`).
- `agy`: Google's [Antigravity CLI](https://antigravity.google/docs/cli), on its subscription, run in an
  empty folder.
- `local`: an AI model running on your Mac (MLX is Apple's software for that), served on this computer only.

Claude and agy only ever see masked text. Every message, and the list of your documents, goes through the
same masking as `taxtrace redact` first: digits become `#`, and words outside the IRS's own vocabulary
become `*`s. A question with an amount in it, or a name from `redact-terms.txt`, isn't sent to them at all:
the model on your Mac answers it, and the page says why. Under each question a cloud model answered, the
page shows exactly what it was sent. The chat reads only the document list and what you type: it can't open
a document, change a file or file anything.

### Always on (macOS)

An installed app (the page added to your Dock from the browser) only works while the server is running.
To start it at login and restart it if it stops:

```bash
taxtrace service install     # same --port, --models and --keychain as `ui`
taxtrace service status      # running or not, the address, the log
taxtrace service uninstall
```

Run `install` from the shell where `TAXTRACE_HOME` is set: a login item doesn't read your shell profile,
so install writes that workspace path, and a `PATH` that finds `agy` and Homebrew's `ocrmypdf`, into
`~/Library/LaunchAgents/io.github.taxtrace.ui.plist`. No key or password goes in it; Claude's key is still
read from the Keychain. The log is `~/Library/Logs/taxtrace-ui.log`.

To install the page as an app, open http://taxtrace.localhost:8766/ in Chrome and click the install icon at
the right of the address bar (or ⋮ → Cast, save and share → Install page as app). It gets its own window and
Dock icon. `python scripts/make_icons.py` rebuilds the app's PNG icons after an SVG changes.
