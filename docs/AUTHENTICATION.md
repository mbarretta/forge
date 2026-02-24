# Authentication Guide for FORGE External Plugins

FORGE external plugins are installed from git repositories (primarily private GitHub repos). This guide covers how to set up authentication for installing and managing external plugins.

## Overview

FORGE uses **standard git authentication** - the same credentials you use for `git clone` work automatically with `forge plugin install`. No additional authentication configuration is needed beyond what you already have set up for git.

---

## SSH Authentication (Recommended)

SSH key authentication is the most secure and convenient method for private repositories.

### Step 1: Generate SSH Key

If you don't already have an SSH key:

```bash
# Generate new SSH key (ed25519 is recommended)
ssh-keygen -t ed25519 -C "your-email@example.com"

# Or RSA if ed25519 is not supported
ssh-keygen -t rsa -b 4096 -C "your-email@example.com"

# Press Enter to accept default location (~/.ssh/id_ed25519)
# Optionally add a passphrase for extra security
```

### Step 2: Add SSH Key to SSH Agent

```bash
# Start ssh-agent
eval "$(ssh-agent -s)"

# Add your SSH key
ssh-add ~/.ssh/id_ed25519
```

**macOS:** Add to `~/.ssh/config` for automatic loading:

```
Host github.com
  AddKeysToAgent yes
  UseKeychain yes
  IdentityFile ~/.ssh/id_ed25519
```

### Step 3: Add SSH Key to GitHub

```bash
# Copy public key to clipboard
# macOS:
pbcopy < ~/.ssh/id_ed25519.pub

# Linux:
xclip -selection clipboard < ~/.ssh/id_ed25519.pub

# Or display and copy manually:
cat ~/.ssh/id_ed25519.pub
```

Then:
1. Go to https://github.com/settings/keys
2. Click "New SSH key"
3. Paste your public key
4. Give it a descriptive title (e.g., "Work MacBook")
5. Click "Add SSH key"

### Step 4: Test SSH Connection

```bash
# Test connection to GitHub
ssh -T git@github.com

# Expected output:
# Hi username! You've successfully authenticated, but GitHub does not provide shell access.
```

### Step 5: Use SSH URLs in Plugin Registry

External plugins in `plugins-registry.yaml` should use SSH URLs:

```yaml
external_plugins:
  my-plugin:
    package: "my-plugin"
    source: "git+ssh://git@github.com/chainguard-dev/my-plugin.git"
    ref: "v1.0.0"
    private: true
```

### Install Plugin with SSH

```bash
# List available plugins
forge plugin list

# Install via SSH (uses your SSH key automatically)
forge plugin install my-plugin
```

---

## HTTPS Authentication

HTTPS authentication uses GitHub personal access tokens or credentials stored by git.

### Option 1: GitHub Personal Access Token (Recommended for HTTPS)

#### Create Token

1. Go to https://github.com/settings/tokens
2. Click "Generate new token" → "Generate new token (classic)"
3. Give it a descriptive name (e.g., "FORGE plugin installs")
4. Select scopes:
   - ✅ `repo` (Full control of private repositories)
5. Click "Generate token"
6. **Copy the token immediately** (you won't be able to see it again)

#### Configure Git Credentials

**Option A: Git Credential Helper (Secure)**

```bash
# Configure git to store credentials
git config --global credential.helper store

# Or use macOS keychain (more secure)
git config --global credential.helper osxkeychain

# Or use Linux secret service
git config --global credential.helper libsecret
```

Then clone any private repo - you'll be prompted once:

```bash
# Clone private repo (will prompt for credentials)
git clone https://github.com/chainguard-dev/private-repo.git

# Username: your-github-username
# Password: <paste your personal access token>

# Credentials are now cached for future use
```

**Option B: Git Credential via gh CLI**

```bash
# Install GitHub CLI
brew install gh  # macOS
# or: https://github.com/cli/cli#installation

# Authenticate
gh auth login

# gh configures git credentials automatically
```

**Option C: Manual URL with Token (Less Secure)**

```bash
# Embed token in URL (not recommended for security reasons)
uv pip install git+https://YOUR_TOKEN@github.com/org/repo.git
```

### Use HTTPS URLs in Plugin Registry

```yaml
external_plugins:
  my-plugin:
    package: "my-plugin"
    source: "git+https://github.com/chainguard-dev/my-plugin.git"
    ref: "v1.0.0"
    private: true
```

### Install Plugin with HTTPS

```bash
# Install via HTTPS (uses cached credentials)
forge plugin install my-plugin
```

---

## GitHub CLI Integration (Easiest)

The GitHub CLI (`gh`) provides the simplest authentication setup.

### Install gh

```bash
# macOS
brew install gh

# Linux (Debian/Ubuntu)
sudo apt install gh

# Other platforms: https://github.com/cli/cli#installation
```

### Authenticate

```bash
# Interactive authentication
gh auth login

# Follow prompts:
# - What account: GitHub.com
# - Protocol: HTTPS or SSH (choose your preference)
# - Authenticate: Browser or Token
```

The `gh` CLI automatically configures git credentials for you.

### Verify Authentication

```bash
# Check authentication status
gh auth status

# Test access to private repo
gh repo view chainguard-dev/private-repo
```

### Use with FORGE

Once `gh` is authenticated, FORGE plugin installs work automatically:

```bash
forge plugin install my-plugin
```

---

## Binary Plugin Downloads (`github_release`)

Some plugins use the `github_release` system dep manager to download pre-built binaries from
GitHub Releases instead of building from source. Authentication works via the `gh` CLI or a
`GITHUB_TOKEN` environment variable.

### Public releases

No authentication needed — binaries on public repos download without credentials.

### Private releases (recommended: `gh` CLI)

If you have the `gh` CLI installed and authenticated (`gh auth login`), FORGE uses it
automatically:

```bash
# One-time setup
gh auth login

# Plugin install picks this up automatically
forge plugin install my-binary-plugin
```

### Private releases (CI / no `gh` CLI): `GITHUB_TOKEN`

```bash
# Set in your shell or CI environment
export GITHUB_TOKEN=ghp_...

forge plugin install my-binary-plugin
```

In GitHub Actions, `${{ secrets.GITHUB_TOKEN }}` is already available:

```yaml
- name: Install FORGE binary plugin
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: forge plugin install my-binary-plugin
```

### Verify access

```bash
# Check gh authentication
gh auth status

# Test access to a private release
gh release list --repo org/my-binary-plugin
```

---

## Organizational Access

For private repositories in GitHub organizations, ensure you have proper access.

### Check Repository Access

```bash
# Via gh CLI
gh repo view chainguard-dev/my-plugin

# Via git
git ls-remote git@github.com:chainguard-dev/my-plugin.git
```

### Request Access

If you see "Repository not found" or "Permission denied":

1. **Contact repository admin** to grant you access
2. **For organizations:** You may need to join a team with repo access
3. **For SSO-enabled orgs:** Authorize your SSH key/token for SSO:
   - Go to https://github.com/settings/keys (for SSH)
   - Or https://github.com/settings/tokens (for tokens)
   - Click "Configure SSO" next to your key/token
   - Authorize for your organization

---

## Troubleshooting

### "Permission denied (publickey)"

**SSH authentication failing:**

```bash
# 1. Check if SSH key exists
ls -la ~/.ssh/id_*.pub

# 2. Test SSH connection
ssh -T git@github.com

# 3. Check SSH agent
ssh-add -l

# 4. Add key to agent if missing
ssh-add ~/.ssh/id_ed25519

# 5. Verify key is added to GitHub
# Visit: https://github.com/settings/keys
```

### "Repository not found"

**HTTPS or SSH access denied:**

```bash
# 1. Check if you have access
gh repo view org/repo

# 2. Verify credentials are configured
git config --global credential.helper

# 3. Test manual clone
git clone git@github.com:org/repo.git

# 4. Check organization membership
gh api user/orgs
```

### "Authentication failed"

**HTTPS token issues:**

```bash
# 1. Check if token is expired
# Visit: https://github.com/settings/tokens

# 2. Generate new token with correct scopes
# Required: repo (for private repos)

# 3. Clear cached credentials
git credential-cache exit

# Or remove from credential store
# macOS: Open Keychain Access, search for "github.com", delete entry
# Linux: rm ~/.git-credentials

# 4. Re-authenticate
git clone https://github.com/org/repo.git
# Enter username and NEW token when prompted
```

### "Could not resolve host"

**Network/DNS issues:**

```bash
# 1. Check internet connection
ping github.com

# 2. Check DNS resolution
nslookup github.com

# 3. Try different DNS (e.g., 8.8.8.8)
# Or use VPN if behind corporate firewall
```

### Plugin Install Fails with Git Error

**FORGE plugin install showing git errors:**

```bash
# 1. Test git access manually
git clone <source-url-from-registry>

# 2. Check UV is using correct git
uv --version
which git

# 3. Try direct installation to debug
uv pip install git+ssh://git@github.com/org/plugin.git

# 4. Check registry URL is correct
grep -A5 "plugin-name" packages/forge-cli/src/forge_cli/data/plugins-registry.yaml
```

---

## Security Best Practices

### 1. Use SSH Keys Over HTTPS Tokens

SSH keys are more secure and easier to manage:
- No need to embed secrets in URLs
- Easier revocation (remove from GitHub)
- Work with multiple accounts via SSH config

### 2. Protect Your Private Keys

```bash
# SSH key files should have restricted permissions
chmod 600 ~/.ssh/id_ed25519
chmod 644 ~/.ssh/id_ed25519.pub

# Never commit private keys to git
# Ensure ~/.ssh/* is in global gitignore
```

### 3. Use Token Scopes Minimally

For GitHub personal access tokens:
- Only enable `repo` scope (no admin or delete permissions)
- Set token expiration (90 days recommended)
- Create separate tokens for different purposes

### 4. Rotate Credentials Regularly

```bash
# SSH: Generate new key annually
ssh-keygen -t ed25519 -C "your-email@example.com"

# HTTPS: Regenerate token annually
# Visit: https://github.com/settings/tokens
```

### 5. Use Credential Helpers

Don't store credentials in plaintext:

```bash
# macOS: Use keychain
git config --global credential.helper osxkeychain

# Linux: Use secret service
git config --global credential.helper libsecret

# Don't use: credential.helper store (plaintext ~/.git-credentials)
```

---

## Environment-Specific Setup

### CI/CD (GitHub Actions)

```yaml
# .github/workflows/install-plugins.yml
jobs:
  install:
    runs-on: ubuntu-latest
    steps:
      - name: Configure git credentials
        run: |
          git config --global credential.helper store
          echo "https://${{ secrets.GITHUB_TOKEN }}@github.com" > ~/.git-credentials

      - name: Install FORGE plugins
        run: |
          forge plugin install my-plugin
```

### Docker Containers

**Option 1: SSH Key Mount**

```dockerfile
# Dockerfile
FROM cgr.dev/chainguard/python:latest

# Install FORGE
RUN uv pip install forge

# SSH key provided at runtime
# docker run -v ~/.ssh:/root/.ssh:ro ...
```

```bash
# Run with SSH key mounted
docker run -v ~/.ssh:/root/.ssh:ro forge-image forge plugin install my-plugin
```

**Option 2: Build-time Secret**

```dockerfile
# syntax=docker/dockerfile:1.4
FROM cgr.dev/chainguard/python:latest

# Use BuildKit secret
RUN --mount=type=ssh \
    forge plugin install my-plugin
```

```bash
# Build with SSH agent forwarding
docker buildx build --ssh default .
```

### Remote Servers

**Transfer SSH key securely:**

```bash
# Copy SSH key to remote server
ssh-copy-id -i ~/.ssh/id_ed25519.pub user@remote-server

# Or manually:
cat ~/.ssh/id_ed25519.pub | ssh user@remote-server "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"

# SSH to remote server
ssh user@remote-server

# On remote: verify SSH key works
ssh -T git@github.com

# Install plugins
forge plugin install my-plugin
```

---

## Quick Reference

### SSH Setup (Recommended)

```bash
# Generate key
ssh-keygen -t ed25519 -C "your-email@example.com"

# Add to GitHub
cat ~/.ssh/id_ed25519.pub  # Copy and paste to github.com/settings/keys

# Test
ssh -T git@github.com

# Use with FORGE
forge plugin install my-plugin  # Uses SSH automatically
```

### HTTPS Setup (Alternative)

```bash
# Option 1: GitHub CLI
gh auth login
forge plugin install my-plugin

# Option 2: Personal Access Token
git config --global credential.helper osxkeychain
git clone https://github.com/org/private-repo.git  # Enter token when prompted
forge plugin install my-plugin
```

### Verify Access

```bash
# Check GitHub authentication
gh auth status

# Check SSH key
ssh -T git@github.com

# Check git credentials
git config --global credential.helper

# Test plugin registry access
forge plugin list
```

---

## Support

**Authentication issues?**
- Check GitHub status: https://www.githubstatus.com/
- Verify repository access: `gh repo view org/repo`
- Test manual git clone: `git clone git@github.com:org/repo.git`

**Still having issues?**
- GitHub docs: https://docs.github.com/en/authentication
- FORGE issues: https://github.com/chainguard-dev/forge/issues
