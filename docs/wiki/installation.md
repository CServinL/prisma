# Installation

Prisma is a PyPI module. Install it once, use the `prisma` command — same pattern as `pip` or `jupyter`.

---

## Regular Users

```bash
python -m venv ~/envs/research
source ~/envs/research/bin/activate
pip install prisma
prisma --help
```

To upgrade:
```bash
pip install --upgrade prisma
```

To pin a version:
```bash
pip install "prisma==0.2.1"
```

> Always use a venv. Never `sudo pip install`.

---

## Developers (editable install)

Editable mode installs a pointer to the repo instead of copying files. Changes to source are immediately active — no reinstall needed.

The runtime venv lives at the XDG data path. `docu-craft` is also a local package and must be installed first.

```bash
# 1. Create the runtime venv (XDG standard location)
python3 -m venv ~/.local/share/prisma/venv

# 2. Upgrade pip first (avoids a Python 3.14 MetadataFile bug in older pip)
~/.local/share/prisma/venv/bin/python3 -m pip install --upgrade pip

# 3. Install docu-craft then prisma (both editable)
~/.local/share/prisma/venv/bin/pip install \
    -e /path/to/docu-craft \
    -e /path/to/prisma

# 4. Expose the CLI via ~/.local/bin (XDG user executables)
mkdir -p ~/.local/bin
ln -sf ~/.local/share/prisma/venv/bin/prisma ~/.local/bin/prisma

# 5. Add ~/.local/bin to PATH (add to ~/.bashrc if not already there)
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

prisma --help
```

Daily workflow — no activation needed, the symlink handles it:
```bash
# edit files, run prisma — changes are live
prisma serve
prisma streams list
```

For running tests, use the project's own `.venv` instead:
```bash
cd /path/to/prisma
.venv/bin/pytest tests/
```

How it works: `pip install -e .` creates `__editable__.prisma-*.pth` in the venv's `site-packages/`, pointing Python at your repo root. The symlink at `~/.local/bin/prisma` calls into the venv without needing `source activate`.

XDG paths used:

| Path | Purpose |
|---|---|
| `~/.local/share/prisma/venv` | Runtime venv |
| `~/.local/bin/prisma` | CLI symlink |
| `~/.config/prisma-desktop/settings.json` | Desktop app settings |
| `~/prisma-vault` | Default vault root (configurable) |

---

## Service Dependencies

### Ollama (LLM)

For WSL, install Ollama on **Windows** so it can use the GPU.

**Windows (PowerShell):**
```powershell
winget install Ollama.Ollama
setx OLLAMA_HOST "0.0.0.0:11434"   # allow WSL to connect
# restart Ollama, then:
ollama pull llama3.1:8b
```

Pull the required models (once, after install and after each Ollama upgrade):

| Model | Purpose |
|---|---|
| `ollama pull llama3.1:8b` | Default LLM for analysis and chat |
| `ollama pull prisma-kg:7b` | Knowledge graph extraction |
| `ollama pull nomic-embed-text` | Semantic embeddings (ChromaDB vector search) |

> **Upgrade note:** after `pip install --upgrade prisma`, re-run `ollama pull nomic-embed-text` if the configured embedding model changes — check `retrieval.embedding_model` in `config.yaml`.

**From WSL:**
```bash
WINDOWS_IP=$(ip route show | grep default | awk '{print $3}')
curl http://${WINDOWS_IP}:11434/api/version   # verify connection
```

Add to `~/.bashrc`:
```bash
export OLLAMA_HOST=$(ip route show | grep default | awk '{print $3}'):11434
```

### Zotero

Install **Zotero Desktop on Windows**. It exposes a local read-only HTTP API on port `23119`.

For writes (creating items and collections), you also need a **Zotero Web API key**:
1. Go to `https://www.zotero.org/settings/keys/new`
2. Create a key with read + write access
3. Note your **User ID** from `https://www.zotero.org/settings/keys`

From WSL, Zotero's local API is at the Windows host IP:
```bash
WINDOWS_IP=$(ip route show | grep default | awk '{print $3}')
curl http://${WINDOWS_IP}:23119/api/
```

---

## Configuration

```bash
mkdir -p ~/.config/prisma
cp /path/to/repo/config.example.yaml ~/.config/prisma/config.yaml
# edit with your Zotero credentials and Windows host IPs
```

Full reference: [Configuration](configuration.md)

---

## Desktop App (Tauri shell — Linux / WSL2)

The Tauri shell opens a native window pointed at `http://127.0.0.1:8765/app`. It requires `prisma serve` to be running first.

### Install Tauri CLI (once)

Install via cargo — do **not** use `npm install @tauri-apps/cli`:

```bash
cargo install tauri-cli --locked
```

This places `tauri` at `~/.cargo/bin/tauri`. Verify: `tauri --version`.

### Build the UI (once, after cloning or after UI changes)

```bash
cd /path/to/prisma/ui
npm install
npm run build        # output → ui/build/ — served by prisma serve at /app
```

### Run the shell

```bash
# terminal 1
prisma serve         # also watches ui/src/ and rebuilds on change

# terminal 2
cd /path/to/prisma-desktop
PKG_CONFIG_PATH=/usr/lib/x86_64-linux-gnu/pkgconfig ~/.cargo/bin/cargo-tauri dev
```

Aliases (add to `~/.bashrc`):
```bash
alias prisma-serve='cd ~/Repos/CServinL/prisma && .venv/bin/prisma serve'
alias prisma-desktop='cd ~/Repos/CServinL/prisma-desktop && PKG_CONFIG_PATH=/usr/lib/x86_64-linux-gnu/pkgconfig ~/.cargo/bin/cargo-tauri dev'
alias prisma-ui-build='cd ~/Repos/CServinL/prisma/ui && npm run build'
```

### Browser / PWA (macOS, iOS, Android)

Open `http://<server-host>:8765/app` in a browser. On Android and iOS, use "Add to home screen" to install as a PWA.

---

## Verify Everything

```bash
prisma status --verbose
prisma zotero test-connection
```
