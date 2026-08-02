<p align="center">
  <img src="public/logo.svg" alt="PRPilot Logo" width="110" height="110">
</p>

<h1 align="center">PRPilot — AI Code Reviews for GitHub</h1>

<p align="center">
  <strong>Automated, multi-model AI code reviews delivered instantly to your GitHub Pull Requests. Free forever.</strong>
</p>

<p align="center">
  <a href="https://prpilot-one.vercel.app" target="_blank">🌐 Live App</a> •
  <a href="https://github.com/apps/prpilot-mirzasayzz" target="_blank">🤖 Install the GitHub App</a>
</p>

<p align="center">
  <a href="#-what-is-prpilot">About</a> •
  <a href="#-features">Features</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-installation">Installation</a> •
  <a href="#️-architecture">Architecture</a> •
  <a href="#-deployment">Deployment</a> •
  <a href="docs/TESTING_GUIDE.md">🧪 Testing Guide</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9+-3776AB?logo=python&logoColor=white" alt="Python Version">
  <img src="https://img.shields.io/badge/Platform-Vercel_Serverless-000000?logo=vercel&logoColor=white" alt="Vercel">
  <img src="https://img.shields.io/badge/GitHub-App-181717?logo=github&logoColor=white" alt="GitHub App">
  <img src="https://img.shields.io/badge/AI-Multi--Model_Failover-e3b862?logo=google&logoColor=white" alt="AI Multi-Model">
  <img src="https://img.shields.io/badge/Database-Supabase-3ecf8e?logo=supabase&logoColor=white" alt="Supabase">
  <img src="https://img.shields.io/badge/License-MIT-2EA043?logo=open-source-initiative&logoColor=white" alt="MIT License">
</p>

---

## 🎯 What is PRPilot?

**PRPilot** is a production-ready GitHub App that brings a highly available, AI-powered team of security researchers, logic validators, and performance architects directly into your CI/CD pipeline.

The moment you open a Pull Request, PRPilot analyzes the code diff across **4 specialized analysis agents** and posts a categorized review — critical, warning, and passing checks — directly on your PR. An advanced **Multi-LLM failover chain** (Gemini → Groq → Cerebras → OpenRouter → LLMApi) ensures reviews never fail due to rate limits or API outages.

---

## 📸 In Action

<p align="center">
  <img src="docs/screenshots/prpilotgithubapp.png" alt="PRPilot GitHub App" width="100%" style="border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
  <br><em>Install PRPilot directly from GitHub to ignite automated reviews</em>
</p>

---

## ✨ Enterprise-Grade Features

### 🤖 Specialized AI Agents
PRPilot avoids generic LLM responses by breaking reviews down into strict concurrent domains:

| Agent | Responsibilities |
|-------|-------------|
| 🎨 **Style & Syntax** | Lint checks, naming conventions, language best practices, formatting |
| 🔒 **Security Scanning** | SQL injection, hardcoded credentials, XSS vectors, authentication flaws |
| ⚡ **Performance Arch** | Big O optimization, memory leak detection, N+1 query warnings |
| 🧠 **Logic & Bounds** | Edge cases, unhandled nulls, missing try-catches, logic regressions |

### 🔄 Multi-LLM High-Availability Architecture
Never suffer from a `429 Rate Limit` failure again. PRPilot uses an automatic fallback chain — if any provider errors, rate-limits, or times out, the next one takes over:
1. **Gemini** — `gemini-2.5-flash`, multi-key rotation via `GEMINI_API_KEYS`.
2. **Groq** — `llama-3.3-70b-versatile` (OpenAI-compatible).
3. **Cerebras** — `gpt-oss-120b` (OpenAI-compatible).
4. **OpenRouter ×2 keys** — `:free` tier models, double quota with two keys.
5. **LLMApi** — `gpt-4o` backup.

Every provider is live-tested before shipping; non-responding providers are skipped automatically with zero downtime.

### 🌟 Additional Highlights
- 🚀 **Zero-Config Install** — Install directly from GitHub; it works out of the box.
- 🔐 **Encrypted Secrets** — API keys are encrypted at rest with Fernet (AES) and decrypted only momentarily at runtime.
- 🗄️ **Review History** — Every review is stored in Supabase for analytics (files reviewed, issues found).
- 🌐 **Polyglot Parsing** — Native support for Python, JS/TS, Go, Java, C++, and more.
- ⚡ **Serverless Delivery** — Delivered on Vercel. Reviews post within 10–30 seconds.

---

## 🚀 Quick Start (Local Testing)

Run the Multi-Agent review lifecycle entirely on your local machine before connecting GitHub:

```bash
# 1. Clone the repository
git clone https://github.com/mirzasayzz/prpilot.git
cd prpilot

# 2. Virtual Environment Setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Secure your secrets locally — copy .env.example to .env and fill in keys
export GEMINI_API_KEY="your-gemini-key"            # Primary (multi-key via GEMINI_API_KEYS also supported)
export GROQ_API_KEY="your-groq-key"                # Fallback 1
export CEREBRAS_API_KEY="your-cerebras-key"        # Fallback 2
export OPENROUTER_API_KEY_1="your-openrouter-key"  # Fallback 3 (+ OPENROUTER_API_KEY_2 for double quota)
export LLMAPI_API_KEY="your-llmapi-key"            # Backup

# GitHub App + Supabase (required for live PR reviews)
export GITHUB_APP_ID="your-app-id"
export GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----"
export GITHUB_WEBHOOK_SECRET="your-webhook-secret"
export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_SERVICE_KEY="your-service-role-key"
export ENCRYPTION_KEY="your-32-byte-fernet-key"

# 4. Trigger localized analysis
python test_local.py test_samples/sample_code.py
```

<details>
<summary><b>Click to see expected output</b></summary>

```
🤖 PRPilot - Local Test (Multi-Provider Active)
Agents: style, security, performance, logic

📁 Reviewing: test_samples/sample_code.py
📏 Lines: 103

🎨 Style Agent analyzing...    ✅ No issues found
🔒 Security Agent analyzing... 🔴 Critical: 2 issues found
⚡ Performance Agent analyzing... 🟡 Warning: 1 issue found
🧠 Logic Agent analyzing...    ✅ No issues found

📊 SUMMARY: 3 issues identified. 
```
</details>

---

## 📦 Installation & GitHub Delivery

### Method A: Single-Click App Installation
1. Navigate to: **[github.com/apps/prpilot-mirzasayzz](https://github.com/apps/prpilot-mirzasayzz)**
2. Click **Install**.
3. Choose to install on `All Repositories` or specific targets.
4. **Done.** Opening or updating a Pull Request automatically triggers the review.

> 📖 See the **[Testing Guide](docs/TESTING_GUIDE.md)** for detailed verification workflows.

---

## 🏗️ Architecture Design

### Routing & High Availability Fallbacks

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#ffffff', 'edgeLabelBackground':'#e1e1e1' }}}%%
flowchart TB
    A["👤 Developer pushes\nPull Request"] --> B["⚡ GitHub Webhook"]
    B --> C["🔐 Webhook Validated\nin Vercel Runtime"]
    C --> D["📂 Code Delta Extraction"]
    
    D --> E["🤖 Concurrent Agent Sub-routines"]
    E --> E1["🎨 Style"]
    E --> E2["🔒 Security"]
    E --> E3["⚡ Perf"]
    E --> E4["🧠 Logic"]

    E1 & E2 & E3 & E4 --> Router{"🚦 Multi-Provider\nLLM Router"}
    
    subgraph Multi_LLM_Strategy [Failover Chain]
        Router --> |Primary Pool| G1[Gemini Key 1]
        G1 -. Rate Limited .-> G2[Gemini Key 2]
        G2 -. Rate Limited .-> G3[Gemini Key N...]
        G3 -. Chain Depleted .-> LLM[LLMApi gpt-4o]
        LLM -. API Outage .-> API[APIFreeLLM]
    end
    
    Multi_LLM_Strategy --> F["📝 Results Synthesizer"]
    F --> G["💬 GitHub API\nPosts Output"]

    style A fill:#6366f1,color:#fff
    style G fill:#22c55e,color:#fff
    style Router fill:#f59e0b,color:#fff
```

### Encryption & Data Persistence

```mermaid
%%{init: {'theme': 'neutral'}}%%
flowchart LR
    subgraph User[Client Configuration]
        Key[API Keys]
    end

    subgraph App[Vercel Serverless]
        Encrypt[AES-256 Symmetric]
        Decrypt[Ephemeral Decryption]
    end

    subgraph Storage[Supabase Postgres]
        Encrypted[(AES Blob Ciphertext)]
    end

    Key --> Encrypt
    Encrypt --> Encrypted
    Encrypted --> Decrypt
```

---

## 🚀 Infrastructure Deployment (Hosting it yourself)

Deploying the architecture to your own infrastructure requires Vercel and Supabase.

### 1. Database (Supabase)
1. Initialize a Supabase project.
2. In the **SQL Editor**, execute [`db/schema.sql`](db/schema.sql).
3. Extract your **Project URL** and **service_role** key.

### 2. GitHub App Authority
1. Visit **Developer Settings → GitHub Apps → New GitHub App**.
2. **Webhook URL**: `https://your-domain.vercel.app/api/webhook`
3. **Permissions**: `Pull Requests` (Read & Write), `Contents` (Read).
4. **Events**: `Pull request`.
5. Retain your **App ID** and **`.pem` Private Key**.

### 3. Vercel CI/CD
```bash
# Vercel Configuration
vercel login && vercel link

# GitHub App + webhook
vercel env add GITHUB_APP_ID production
vercel env add GITHUB_PRIVATE_KEY production
vercel env add GITHUB_WEBHOOK_SECRET production

# Supabase (review history)
vercel env add SUPABASE_URL production
vercel env add SUPABASE_SERVICE_KEY production

# Multi-model LLM failover chain
vercel env add GEMINI_API_KEYS production      # Comma-separated (primary)
vercel env add GROQ_API_KEY production         # Fallback 1
vercel env add CEREBRAS_API_KEY production     # Fallback 2
vercel env add OPENROUTER_API_KEY_1 production # Fallback 3
vercel env add OPENROUTER_API_KEY_2 production # Fallback 4 (optional)
vercel env add LLMAPI_API_KEY production       # Backup

# Symmetric encryption key
python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())" | vercel env add ENCRYPTION_KEY production

# Push to edge network
vercel --prod
```

---

## 📁 Repository Map

```
prpilot/
├── api/                        # Serverless entry points
│   ├── webhook.py              # Webhook ingest & signature validation
│   └── config.py               # Application configuration 
├── agents/                     # Code intelligence framework
│   ├── base.py                 # Core agent schema & prompt interfaces
│   ├── style_agent.py          # Syntax specific evaluation
│   ├── security_agent.py       # Vulnerability metrics
│   ├── performance_agent.py    # Algorithmic time-complexity tracking
│   ├── logic_agent.py          # State/Bounds logic checking
│   └── llm_client.py           # Multi-Provider automated failover architecture
├── db/                         # PostgreSQL schema definitions
├── public/                     # Static UI & landing sites
├── docs/                       # Validation & QA procedures
│   └── TESTING_GUIDE.md        
└── test_local.py               # CLI test harness
```

---

## 🤝 Contributing

We rely on the open-source community to build better heuristics.
1. **Fork** the repository
2. **Branch**: `git checkout -b feature/enhanced-routing`
3. **Validate**: Run `test_local.py` ensuring all providers respond.
4. **Push & Pull Request** — PRPilot will automatically review your code.

---

## 📄 License & Compliance

This software is released under the **MIT License**. Operations comply strictly with SOC-ready architectural standards—keys are universally encrypted. See [LICENSE](LICENSE) for granular clauses.

---

<p align="center">
  Architected by <a href="https://github.com/mirzasayzz">mirzasayzz</a>
</p>
