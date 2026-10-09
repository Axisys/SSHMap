# `examples/` — working example plugins

Eight plugins that really load, next to the contract (`PLUGINS.md`) and the walkthrough it
carries in §10. They are **examples, not shipped plugins**:

* they are NOT part of the installed package (`pyproject.toml` lists the packages
  explicitly — `examples/` is not among them);
* they are NEVER auto-discovered — the core reads the entry points of the installed
  packages and `~/.sshmap/plugins/` only;
* they add NO i18n keys: a plugin's strings are the author's (`PLUGINS.md` §7).

One lesson per file — copy the ONE you need:

| File | What it shows |
|---|---|
| `plugins/hello.py` | The minimal plugin, doing the smallest USEFUL thing twice: a Ctrl+K row that copies the plugins folder path (a palette callback **does** receive the context) and a server right-click row that copies an `ssh` command line (a menu hook receives **no** context, so the plugin uses the clipboard itself). |
| `plugins/disk_monitor.py` | The Disk Space Monitor: `run_on_nodes` collects `df -hP` over SSH into the plugin's own atomic cache, `status_probe` turns a filesystem over 90% into a `warn` on the card and a line in its tooltip. No SSH inside a probe. |
| `plugins/systemd_failed.py` | The Systemd Failed Monitor — the SMALLEST honest monitor: ONE command, ONE count, ONE detail line, and the reporter answers `None` (not `online`) at a count of zero, so a plugin can never brighten a card the SSH probe marked down. |
| `plugins/maintenance.py` | The Maintenance Check: TWO facts (`reboot required`, pending updates) as ONE command with a marker protocol, because `ctx.run_command` opens its own connection per node **per call** — and the `timeout=` argument a package manager on a slow mirror needs. |
| `plugins/certificates.py` | The Certificate Monitor — the example that NEVER touches SSH: it reads its own config, opens a TLS connection with `ssl` / `socket` and warns under a horizon, so it has a fact about a host whose SSH is down. No `ctx.run_command` at all, and the connector is an injectable attribute. |
| `plugins/open_ports.py` | The Open Ports Monitor: one `ss -tulpn` per node, the listening sockets normalised (a dual-stack pair collapses to the most EXPOSED binding), the list appended to the tooltip and a watchlisted port that the net can REACH turned into a `warn`. |
| `plugins/app_versions.py` | The App Version Check: ONE generated POSIX-sh probe per node that only COLLECTS evidence, a pure-Python report over it (nginx, Grafana, Loki, Alloy, Prometheus, Tempo, Telegraf, Promtail) and the expected versions in `~/.sshmap/plugins/app_versions.baseline.json`, a data file you own. |
| `plugins/watch_command.py` | The Watch Command — the plugin whose fact is the USER's: its own config maps a node (by ID or by host) to a command, the regex that means `warn` and the detail to show. The command runs verbatim, and the settings file answers "where do a plugin's settings live?". |

## Using them

```bash
# 1. copy (no packaging, no install)
mkdir -p ~/.sshmap/plugins                 # Windows: %USERPROFILE%\.sshmap\plugins
cp examples/plugins/hello.py          ~/.sshmap/plugins/
cp examples/plugins/disk_monitor.py   ~/.sshmap/plugins/
cp examples/plugins/systemd_failed.py ~/.sshmap/plugins/
cp examples/plugins/maintenance.py    ~/.sshmap/plugins/
cp examples/plugins/certificates.py   ~/.sshmap/plugins/
cp examples/plugins/open_ports.py     ~/.sshmap/plugins/
cp examples/plugins/app_versions.py   ~/.sshmap/plugins/
cp examples/plugins/watch_command.py  ~/.sshmap/plugins/

# 2. in the application: Plugins → Reload — eight rows appear, all of them ON
#    (the switch lives in the "plugins" key of ~/.sshmap/config.json)
```

* **`hello`**: press `Ctrl+K` and run *Copy the plugins folder path* (the line lands on the
  clipboard and in the status bar), or right-click a server → *Copy SSH command* — one `ssh -p …`
  line per selected server, ready to paste into a terminal.
* **`disk_monitor`**: select the servers you care about and use **Plugins → Run on selected
  servers**; the status bar reports `disk: N node(s), M over the threshold`, and from the
  next status round a full filesystem shows as `warn` with `/var 92% (threshold 90)` in
  the card's tooltip. Its cache is `~/.sshmap/plugins/disk_monitor.state.json` — delete it
  freely, the next run rebuilds it.
* **`systemd_failed`**: run it the same way; `systemd: N node(s), M with a failed unit` and a
  card that warns with `2 failed: nginx.service, docker.service`. A host without systemd (a
  container, no `systemctl` on `PATH`) or without a failed unit adds NO opinion — the SSH
  status stands. Cache: `systemd_failed.state.json`.
* **`maintenance`**: one probe answers both questions; the card shows
  `reboot required · 12 updates` (the RPM family reports `updates available`, because
  `dnf -q check-update` gives a verdict and no count). The per-node budget is 120 s, so a slow
  mirror does not turn into "no answer". Cache: `maintenance.state.json`.
* **`certificates`**: write `~/.sshmap/plugins/certificates.json` —
  `{"default_port": 443, "horizon_days": 21, "nodes": {"web-1": 8443}}` (a key is a node ID or a
  host; the file is optional, the defaults are 443 and 21 days). Every status round opens one TLS
  connection per node from THIS machine and warns with `certificate expires in 9 day(s) (443/tcp)`.
  No config file is needed and no SSH is used: an unreachable port or a refused handshake is
  silently "no data", and switching the plugin off in the Plugins menu stops the checks.
* **`open_ports`**: the same door collects `ss -tulpn` and reports `ports: N node(s), M with a
  watchlisted port exposed`; an `online` card gains the reachable port list
  (`3 open: 22/tcp, 80/tcp, 443/tcp (+2 on loopback)`) and a database the network can reach turns it
  `warn` (`exposed 3306/tcp (mysqld) - 3 open`). **The Plugins window carries the DATA too** — one line
  per node with the whole cached list, each row marked (`6379/tcp redis-server (exposed)`,
  `3306/tcp (loopback)`), so **Plugins → Export** writes a per-node port report to a text file. Cache:
  `open_ports.state.json`. A host whose `ss` is missing is a log line, never an empty
  "nothing is listening" answer.
* **`app_versions`**: run it the same way (or `Ctrl+K` → *Versions: re-check every known
  server*, which re-probes the fleet of the last collection); every app is reported as
  `web-1: nginx [ok] 1.30.2 (/usr/sbin/nginx)`, and **Plugins → Export** writes the lines to a
  text file. `Ctrl+K` → *Versions: write the baseline file* seeds
  `app_versions.baseline.json` from the last collection — edit the `expected` versions there
  (and `nodes` for a single server) by hand; an existing file is never overwritten.
* **`watch_command`**: `Ctrl+K` → *Watch: write the config template* creates
  `~/.sshmap/plugins/watch_command.json` (an existing file is never overwritten). Fill it in —
  `{"default": null, "nodes": {"web-1": {"command": "uptime", "warn_pattern": "load average: [1-9]",
  "detail": "load is high"}}}` — and a run asks each configured node for ITS OWN command, verbatim;
  the card warns with your detail while the pattern matches. Cache: `watch_command.state.json`.

## Editing them

`Plugins → Reload` re-reads the folder: a changed file is picked up without a restart.

**The one rule all eight files follow: an example plugin never imports the core** (`modules.*`,
`i18n.*`, `ui.*`), uses no `sys.path` trick and opens no SSH connection of its own (the
standard library is the author's business). The application finds plugins without any
cooperation from them, and a user of an installed app has no repository checkout on
`sys.path` — an example that imported `modules.plugin_manager` would work here and break for
that user. The predicate lives ONCE, in `tests/_common.py` (`example_plugin_problems()`), and
the topical files of the folder all read it.

Deeper: the contract and the per-hook reference — `PLUGINS.md`; the implementation —
`DOCUMENTATION.md` §33.
