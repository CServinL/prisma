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

```bash
git clone https://github.com/CServinL/prisma.git
cd prisma
python3 -m venv ~/prisma
source ~/prisma/bin/activate
pip install -e ".[dev]"
prisma --help
```

Daily workflow:
```bash
source ~/prisma/bin/activate
# edit files, run prisma — changes are live
prisma streams list
pytest tests/unit/
```

How it works: `pip install -e .` creates `__editable__.prisma-*.pth` in the venv's `site-packages/`, pointing Python at your repo root. The `prisma` binary in `~/prisma/bin/` calls `prisma.cli.prisma_cli:cli` which resolves directly to your repo.

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

## Verify Everything

```bash
source ~/prisma/bin/activate   # or your venv
prisma status --verbose
prisma zotero test-connection
```
