# Development Setup Guide

This guide covers the complete setup process for developing and running Prisma on WSL (Windows Subsystem for Linux) or native Linux systems.

## Prerequisites

- WSL2 (Windows) or native Linux distribution (Ubuntu 20.04+ recommended)
- Python 3.12+ 
- Git
- Internet connection for downloading models and accessing APIs

## 1. Zotero Setup and Integration

Prisma supports both local Zotero database access and cloud-based Zotero Web API integration for accessing your research library.

### Option A: Zotero Web API Integration (Recommended)

The Zotero Web API provides reliable cloud-based access to your Zotero library with full synchronization support.

#### Step 1: Create Zotero API Key

1. Go to [https://www.zotero.org/settings/keys/new](https://www.zotero.org/settings/keys/new)
2. Log in to your Zotero account
3. Create a new API key with these settings:
   - **Description**: "Prisma Literature Review Tool"
   - **Key Type**: Personal
   - **Permissions**: 
     - ✅ Allow library access
     - ✅ Allow notes access
     - ✅ Allow write access (optional)
   - **Default Group Permissions**: Read (if you want to access group libraries)

4. Copy the generated API key (you'll need this for configuration)

#### Step 2: Find Your Library ID

**For Personal Library:**
- Your User ID is shown on the API Keys page
- Or go to [https://www.zotero.org/settings/keys](https://www.zotero.org/settings/keys) and note the number in the URL

**For Group Library:**
- Go to your group's page on zotero.org
- The group ID is in the URL: `https://www.zotero.org/groups/[GROUP_ID]/`

#### Step 3: Configure Prisma

Create or update your Prisma configuration file at `~/.config/prisma/config.yaml`:

```yaml
sources:
  zotero:
    enabled: true
    api_key: "YOUR_API_KEY_HERE"
    library_id: "YOUR_LIBRARY_ID"
    library_type: "user"  # or "group" for group libraries
    default_collections: []  # Optional: specific collection keys to search by default
    include_notes: false
    include_attachments: false

# Other existing configuration...
llm:
  provider: 'ollama'
  model: 'llama3.1:8b'
  host: '172.29.32.1:11434'

output:
  directory: './outputs'
  format: 'markdown'

search:
  default_limit: 10
  sources: ['arxiv', 'zotero']  # Include zotero in default sources
```

#### Step 4: Test Zotero Integration

```bash
# Test the connection
python -c "
from src.integrations.zotero import ZoteroClient, ZoteroConfig
config = ZoteroConfig(api_key='YOUR_KEY', library_id='YOUR_ID')
client = ZoteroClient(config)
print('Connection successful!' if client.test_connection() else 'Connection failed!')
"

# Test CLI with Zotero
python src/cli/main.py --topic "machine learning" --zotero-only --limit 5
```

### Option B: Local Zotero Database Access (Alternative)

If you prefer to use a local Zotero installation, you can access the SQLite database directly.

#### Install Zotero in WSL/Linux

```bash
# Update package lists
sudo apt update

# Install required dependencies
sudo apt install -y wget curl software-properties-common sqlite3

# Method 1: Install via Snap (Most Reliable)
sudo snap install zotero-snap

# Method 2: Alternative - Try retorquere repository (if snap fails)
# wget -qO- https://github.com/retorquere/zotero-deb/releases/latest/download/install.sh | sudo bash
# sudo apt update
# sudo apt install zotero

# Verify installation
zotero-snap --version
```

#### Configure Local Database Access

Update your `~/.config/prisma/config.yaml`:

```yaml
sources:
  zotero:
    enabled: false  # Disable API integration
    # Local database paths (for legacy support)
    library_path: "/home/username/snap/zotero-snap/common/Zotero/zotero.sqlite"
    data_directory: "/home/username/snap/zotero-snap/common/Zotero/"
```

### Option C: Use Existing Windows Zotero Installation

If you already have Zotero installed on Windows, you can access its database from WSL:

```bash
# Find your Zotero profile directory (typical location)
ls /mnt/c/Users/$USER/Zotero/

# Example database path for configuration
# /mnt/c/Users/YourUsername/Zotero/zotero.sqlite
```

### Setting Up Zotero Data Directory

```bash
# Create Zotero data directory in WSL (if using Option A)
mkdir -p ~/.config/zotero
mkdir -p ~/Zotero

# For snap installation, Zotero data will be in:
# ~/snap/zotero-snap/common/ (when you first run Zotero)

# For Option B, create a symlink to Windows Zotero data
# Replace YourUsername with your actual Windows username
ln -s /mnt/c/Users/YourUsername/Zotero ~/Zotero-Windows
```

### Zotero Database Location

Your Zotero database will be located at:
- **Option A (Snap Zotero)**: `~/snap/zotero-snap/common/Zotero/zotero.sqlite` (after first run)
- **Option A (APT Zotero)**: `~/Zotero/zotero.sqlite` 
- **Option B (Windows Zotero)**: `/mnt/c/Users/YourUsername/Zotero/zotero.sqlite`

**Note**: Make sure Zotero is closed when Prisma accesses the database to avoid file locking issues.

### Initialize Zotero Database

```bash
# For snap installation, run Zotero once to create the database
timeout 10s zotero-snap  # Starts Zotero briefly then closes

# Verify database was created
ls -la ~/snap/zotero-snap/common/Zotero/zotero.sqlite

# If database doesn't exist, run Zotero manually and close it
# The database will be created on first launch
```

## 2. Ollama Setup in WSL/Linux

Ollama provides local LLM capabilities for AI-powered paper analysis and summarization.

### Option A: WSL Setup (Windows + WSL2)

**For WSL users, install Ollama on Windows host instead of inside WSL to avoid GPU issues.**

```bash
# 1. Install Ollama on Windows (run in Windows PowerShell/CMD, not WSL):
# Download from https://ollama.ai/download/windows
# Or use winget: winget install Ollama.Ollama

# 2. Configure Ollama to accept connections from WSL
# In Windows PowerShell/CMD, set environment variable:
# setx OLLAMA_HOST "0.0.0.0:11434"
# Then restart Ollama application

# 3. Get Windows host IP from WSL (use the default gateway, not DNS)
export WINDOWS_HOST_IP=$(ip route show | grep default | awk '{print $3}')
echo "Windows host IP: $WINDOWS_HOST_IP"

# Important: The Windows host IP can vary (172.x.x.x, 192.168.x.x, etc.)
# Dynamic discovery is more reliable than hardcoded IPs

# 4. In WSL, configure to use Windows Ollama IP
echo "export OLLAMA_HOST=${WINDOWS_HOST_IP}:11434" >> ~/.bashrc
source ~/.bashrc

# 5. Test connection from WSL
curl http://${WINDOWS_HOST_IP}:11434/api/version
```

**Download models from Windows:**
```powershell
# Run these commands in Windows PowerShell/CMD
ollama pull llama3.1:8b
ollama pull mistral:7b
ollama list
```

**Alternative: Download via API (if PowerShell unavailable):**
```bash
# If you can't access Windows PowerShell, use API from WSL
export WINDOWS_HOST_IP=$(ip route show | grep default | awk '{print $3}')

# Download llama3.1:8b via API
curl -X POST http://${WINDOWS_HOST_IP}:11434/api/pull \
  -H "Content-Type: application/json" \
  -d '{"name": "llama3.1:8b"}'

# Download mistral:7b via API  
curl -X POST http://${WINDOWS_HOST_IP}:11434/api/pull \
  -H "Content-Type: application/json" \
  -d '{"name": "mistral:7b"}'

# Verify models are downloaded
curl -X GET http://${WINDOWS_HOST_IP}:11434/api/tags
```

### Option B: Native Linux Setup

```bash
# Download and install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Verify installation
ollama --version

# Start Ollama service (if not auto-started)
ollama serve &
```

### Download Required Models

**For WSL users (using Windows Ollama):**
```powershell
# Run in Windows PowerShell/CMD
ollama pull llama3.1:8b
ollama pull mistral:7b
ollama list
```

**For native Linux users:**
```bash
# Primary model for paper analysis (recommended)
ollama pull llama3.1:8b

# Alternative smaller model for faster processing
ollama pull llama3.1:latest

# Specialized model for summarization (optional)
ollama pull mistral:7b

# Verify models are installed
ollama list
```

### Configure Ollama for Prisma

**For WSL users:**
```bash
# Set environment variables (add to ~/.bashrc for persistence)
# Use the Windows host IP discovered during setup
export WINDOWS_HOST_IP=$(ip route show | grep default | awk '{print $3}')
echo "export OLLAMA_HOST=${WINDOWS_HOST_IP}:11434" >> ~/.bashrc
echo 'export OLLAMA_MODEL=llama3.1:8b' >> ~/.bashrc
source ~/.bashrc

# Test from WSL
curl http://${WINDOWS_HOST_IP}:11434/api/version
```

**For native Linux users:**
```bash
# Test Ollama is working
ollama run llama3.1:8b "Summarize the concept of machine learning in one sentence."

# Set environment variables (add to ~/.bashrc for persistence)
echo 'export OLLAMA_HOST=localhost:11434' >> ~/.bashrc
echo 'export OLLAMA_MODEL=llama3.1:8b' >> ~/.bashrc
source ~/.bashrc
```

### Ollama Performance Tips

**For WSL users:**
```bash
# WSL will use Windows GPU automatically through Ollama on Windows
# No special configuration needed

# Check connection using your Windows host IP
export WINDOWS_HOST_IP=$(ip route show | grep default | awk '{print $3}')
curl http://${WINDOWS_HOST_IP}:11434/api/version

# Monitor from Windows Task Manager for resource usage
```

**For native Linux users:**
```bash
# Check available memory
free -h

# For systems with limited RAM, use smaller models
ollama pull gemma2:2b

# Monitor Ollama resource usage
htop
```

## 3. Prisma Setup in WSL/Linux

Now set up the Prisma development environment with all dependencies.

### Clone and Setup Repository

```bash
# Clone the repository
git clone https://github.com/CServinL/prisma.git
cd prisma

# Verify Python version
python3 --version  # Should be 3.12+

# Install pipx for Python package management
sudo apt install -y pipx
pipx ensurepath

# Restart shell or source bashrc
source ~/.bashrc
```

### Install Dependencies

```bash
# Install pipenv using pipx
pipx install pipenv

# Install project dependencies
pipenv install --dev

# Verify installation
pipenv --version
```

### Configuration Setup

```bash
# Create configuration directory
mkdir -p ~/.config/prisma

# Since config/example.yaml doesn't exist yet, create configuration manually
# Edit configuration with your paths
nano ~/.config/prisma/config.yaml
```

Create the configuration file with your specific paths:

```yaml
# ~/.config/prisma/config.yaml
sources:
  zotero:
    library_path: "/home/yourusername/snap/zotero-snap/common/Zotero/zotero.sqlite"  # Snap Zotero path
    data_directory: "/home/yourusername/snap/zotero-snap/common/Zotero/"
  
llm:
  provider: "ollama"
  model: "llama3.1:8b"
  host: "172.29.32.1:11434"  # Use your actual Windows host IP for WSL

output:
  directory: "./outputs"
  format: "markdown"

# Optional settings  
search:
  default_limit: 10
  sources: ["arxiv"]

analysis:
  summary_length: "medium"
  
logging:
  level: "INFO"
  file: "./logs/prisma.log"
```

**Important**: Replace `yourusername` with your actual username, and update the IP address with your Windows host IP discovered during setup.

### Verify Installation

```bash
# Activate virtual environment
pipenv shell

# Test CLI is working
python src/cli/main.py --help

# Test basic functionality (requires Zotero and Ollama running)
python src/cli/main.py --topic "test" --limit 1 --output "test_output.md"
```

### Environment Variables

Add these to your `~/.bashrc` for convenience:

```bash
# Add to ~/.bashrc
echo 'export PRISMA_CONFIG=~/.config/prisma/config.yaml' >> ~/.bashrc
echo 'export PRISMA_DATA_DIR=~/prisma-data' >> ~/.bashrc
echo 'alias prisma="cd ~/prisma && pipenv run python src/cli/main.py"' >> ~/.bashrc

# Reload
source ~/.bashrc
```

### Troubleshooting

#### Common Issues:

**1. Zotero Database Access Issues:**
```bash
# Check if Zotero is running (close it if needed)
ps aux | grep zotero

# Verify database permissions
ls -la ~/Zotero/zotero.sqlite
```

**2. Ollama Connection Issues:**

**For WSL users:**
```bash
# Check if Windows Ollama is accessible from WSL
# Use the same IP discovery method from setup
export WINDOWS_HOST_IP=$(ip route show | grep default | awk '{print $3}')
curl http://${WINDOWS_HOST_IP}:11434/api/version

# If connection fails, ensure Ollama is running on Windows:
# - Check Windows System Tray for Ollama icon
# - Or restart Ollama from Windows Start Menu

# Test Windows Ollama from PowerShell:
# ollama list
```

**For native Linux users:**
```bash
# Check if Ollama is running
curl http://localhost:11434/api/version

# Check service status
sudo systemctl status ollama.service

# Restart Ollama if needed
sudo systemctl restart ollama.service

# Test model execution
ollama run llama3.1:8b "test"
```

**3. Python/Pipenv Issues:**
```bash
# Clear pipenv cache
pipenv --rm
pipenv install --dev

# Check Python path
which python3

# If pipenv not found, ensure pipx is in PATH
pipx ensurepath
source ~/.bashrc
```

**4. Environment Variable Issues:**
```bash
# Check current environment variables
echo "OLLAMA_HOST: $OLLAMA_HOST"
echo "OLLAMA_MODEL: $OLLAMA_MODEL"

# If duplicates exist in ~/.bashrc, clean them up
cp ~/.bashrc ~/.bashrc.backup
grep -v "export OLLAMA_HOST=" ~/.bashrc > /tmp/bashrc_temp && mv /tmp/bashrc_temp ~/.bashrc

# Re-add clean environment variables
export WINDOWS_HOST_IP=$(ip route show | grep default | awk '{print $3}')
echo "export OLLAMA_HOST=${WINDOWS_HOST_IP}:11434" >> ~/.bashrc
source ~/.bashrc
```

**5. Virtual Environment Context:**
```bash
# Always activate pipenv when working with Prisma
cd ~/prisma
pipenv shell

# If lost terminal session, reactivate
pipenv shell

# Test CLI within virtual environment
python src/cli/main.py --help
```

### Next Steps

With everything set up, you can now:

1. **Test Zotero Integration**: Add some papers to your Zotero library
2. **Verify Ollama Models**: Test paper summarization
3. **Run Full Pipeline**: Execute a complete literature review
4. **Develop Features**: Start working on Day 2+ components

### Development Workflow

```bash
# Daily development routine
cd ~/prisma
pipenv shell
git pull origin main
python src/cli/main.py --topic "your research topic" --limit 5
```

### Debugging and Verification

```bash
# Quick environment verification
echo "=== ENVIRONMENT CHECK ==="
echo "Python: $(python3 --version)"
echo "Pipenv: $(pipenv --version 2>/dev/null || echo 'Not found')"
echo "OLLAMA_HOST: $OLLAMA_HOST"
echo "Zotero DB: $(ls -la ~/snap/zotero-snap/common/Zotero/zotero.sqlite 2>/dev/null || echo 'Not found')"

# Test Ollama connectivity
curl -s http://$OLLAMA_HOST/api/version || echo "Ollama connection failed"

# Test CLI within virtual environment
pipenv run python src/cli/main.py --help | head -3

# Quick functional test
pipenv run python src/cli/main.py --topic "test" --limit 1 --debug
```

You're now ready to develop and use Prisma with full Zotero and Ollama integration!