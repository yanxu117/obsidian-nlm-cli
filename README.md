# obsidian-nlm-cli

> One-way sync from Obsidian vault to Google NotebookLM. Your vault is the source of truth.

## What it does

```
Obsidian Vault ──sync──▸ Google NotebookLM
  📁 folder    ────────▸ 📓 Notebook
  📝 note.md   ────────▸ 📄 Text Source
```

- **Obsidian is authority** — edit locally, sync to NotebookLM
- **Auto-organize** — loose `.md` files in vault root get auto-folded into folders
- **Rename tracking** — rename a folder, the NotebookLM notebook gets renamed
- **Watch mode** — continuous sync every 60 seconds
- **Bootstrap** — pull existing NotebookLM data into a fresh vault

## Quick start

### One-click install

```bash
curl -sSL https://raw.githubusercontent.com/yanxuwang/obsidian-nlm-cli/main/setup.sh | bash
```

### Manual install

```bash
# Requires Python 3.10+
pip install obsidian-nlm-cli notebooklm-mcp-cli

# Authenticate with Google
nlm login
```

## Usage

```bash
# Bootstrap: pull all existing NotebookLM data into your vault
obsidian-nlm bootstrap --vault ~/MyVault

# One-shot sync: push local changes to NotebookLM
obsidian-nlm scan --vault ~/MyVault

# Check sync status
obsidian-nlm status --vault ~/MyVault

# Continuous sync (every 60 seconds)
obsidian-nlm watch --vault ~/MyVault --interval 60
```

You can also set the vault path via environment variable:

```bash
export OBSIDIAN_NLM_VAULT=~/MyVault
obsidian-nlm scan
```

## How it works

1. Each **top-level folder** in your vault maps to a NotebookLM notebook
2. Each **`.md` file** in a folder maps to a text source in that notebook
3. Sync is **one-way**: Obsidian → NotebookLM
4. Notebooks/sources in NotebookLM but not in your vault get **deleted**
5. File content changes are detected via **SHA-256 hashing**

### Managed metadata

Each notebook folder gets a `.notebooklm.json` tracking file.

Each markdown file gets frontmatter:

```yaml
---
nlm_notebook_id: "ab3bbc11-..."
nlm_source_id: "cd4fdd22-..."
nlm_source_type: "text"
nlm_source_url: ""
---
```

Do not hand-edit these fields.

## Auto-start on macOS (launchd)

```bash
cat > ~/Library/LaunchAgents/com.obsidian-nlm.watch.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.obsidian-nlm.watch</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>-m</string>
        <string>obsidian_nlm_cli.cli</string>
        <string>watch</string>
        <string>--vault</string>
        <string>/path/to/your/vault</string>
        <string>--interval</string>
        <string>60</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/obsidian-nlm.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/obsidian-nlm.log</string>
</dict>
</plist>
EOF

launchctl load ~/Library/LaunchAgents/com.obsidian-nlm.watch.plist
```

## Requirements

- Python 3.10+
- [notebooklm-mcp-cli](https://github.com/jacob-bd/notebooklm-mcp-cli) (auto-installed)
- Google account with NotebookLM access

## License

MIT
