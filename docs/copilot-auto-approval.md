# VS Code Auto-Approval Setup for GitHub Copilot

This document explains how to configure auto-approval for test commands when using GitHub Copilot in VS Code.

## Setting Up Auto-Approval

1. **Open VS Code User Settings (JSON):**
   - Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on Mac)
   - Type "Preferences: Open User Settings (JSON)"
   - Select the command

2. **Add the following to your User Settings:**

```json
{
    "chat.tools.terminal.autoApprove": {
        // ... your existing auto-approval settings ...
        
        // Add these lines for pytest auto-approval:
        "pytest": true,
        "python -m pytest": true,
        "pipenv run python -m pytest": true,
        "/^pytest\\b/": true,
        "/^python\\s+-m\\s+pytest\\b/": true,
        "/^pipenv\\s+run\\s+python\\s+-m\\s+pytest\\b/": true
    }
}
```

3. **Save the file** and restart VS Code if needed.

## What This Enables

After configuration, GitHub Copilot will automatically approve these commands without prompting:

- `pytest`
- `python -m pytest`
- `pipenv run python -m pytest`
- Any pytest command variations

## Security Note

Only add commands you trust to auto-approval. Test commands are generally safe, but be cautious with other command patterns.

## Alternative: Manual Approval

If you prefer not to use auto-approval, you can manually approve commands when prompted by GitHub Copilot.

## Troubleshooting

- Make sure you're editing **User Settings**, not **Workspace Settings**
- The settings file is typically located at:
  - Windows: `%APPDATA%\Code\User\settings.json`
  - macOS: `~/Library/Application Support/Code/User/settings.json`
  - Linux: `~/.config/Code/User/settings.json`