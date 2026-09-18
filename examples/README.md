# `examples/` — working example plugins

Two plugins that really load, next to the contract (`PLUGINS.md`) and the walkthrough it
carries in §10. They are **examples, not shipped plugins**:

* they are NOT part of the installed package (`pyproject.toml` lists the packages
  explicitly — `examples/` is not among them);
* they are NEVER auto-discovered — the core reads the entry points of the installed
  packages and `~/.sshmap/plugins/` only;
* they add NO i18n keys: a plugin's strings are the author's (`PLUGINS.md` §7).

| File | What it shows |
|---|---|
| `plugins/hello.py` | The minimal plugin: one command in the Ctrl+K palette (returned as a plain `(text, callback)` pair) and one row in the right-click menu of a server, on the map and in the list alike. |
| `plugins/disk_monitor.py` | The first useful one — the Disk Space Monitor: `run_on_nodes` collects `df -hP` over SSH into the plugin's own atomic cache, `status_probe` turns a filesystem over 90% into a `warn` on the card and a line in its tooltip. No SSH inside a probe. |

## Using them

```bash
# 1. copy (no packaging, no install)
mkdir -p ~/.sshmap/plugins                 # Windows: %USERPROFILE%\.sshmap\plugins
cp examples/plugins/hello.py          ~/.sshmap/plugins/
cp examples/plugins/disk_monitor.py   ~/.sshmap/plugins/

# 2. in the application: Plugins → Reload — both rows appear, both are ON
#    (the switch lives in the "plugins" key of ~/.sshmap/config.json)
```

* **`hello`**: press `Ctrl+K` and run *Say hello*, or right-click a server → *Hello on this server*.
* **`disk_monitor`**: select the servers you care about and use **Plugins → Run on selected
  servers**; the status bar reports `disk: N node(s), M over the threshold`, and from the
  next status round a full filesystem shows as `warn` with `/var 92% (threshold 90)` in
  the card's tooltip. Its cache is `~/.sshmap/plugins/disk_monitor.state.json` — delete it
  freely, the next run rebuilds it.

## Editing them

`Plugins → Reload` re-reads the folder: a changed file is picked up without a restart.

**The one rule both files follow: an example plugin never imports the core** (`modules.*`,
`i18n.*`, `ui.*`). The application finds plugins without any cooperation from them, and a
user of an installed app has no repository checkout on `sys.path` — an example that
imported `modules.plugin_manager` would work here and break for that user.
`tests/test_plugin_examples.py` enforces this with a source scan.

Deeper: the contract and the per-hook reference — `PLUGINS.md`; the implementation —
`DOCUMENTATION.md` §33.
