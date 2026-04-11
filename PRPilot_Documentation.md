# PRPilot: AI-Powered Code Review Bot

## What is PRPilot?
PRPilot is an automated GitHub App that acts as an expert AI code reviewer. Whenever a developer pushes new code or creates a Pull Request (PR) on GitHub, PRPilot automatically reads the new code, analyzes it using advanced AI models (like Google Gemini, Groq, LLMApi, and APIFree), and posts a comment on the PR detailing any issues it found.

Think of it as an automated senior developer that checks your code for security vulnerabilities, logic bugs, performance bottlenecks, and style issues before anyone else has to look at it.

---

## How It Works (The Flow)
1. **Developer opens a Pull Request** on GitHub.
2. **GitHub sends a Webhook (notification)** to our deployed PRPilot backend (hosted on Vercel).
3. **PRPilot's Webhook Handler (`api/webhook.py`)** receives the notification, verifies it came from GitHub securely, and extracts the PR details.
4. **Fetching Code:** PRPilot uses the GitHub API to download the code files that were changed in the PR.
5. **AI Review (`agents/base.py` & `agents/llm_client.py`)**: PRPilot passes the code to its AI agents. The `MultiProviderLLM` client routes the request to an available AI model. If one model (like Gemini) hits a limit, it instantly falls back to another (like LLMApi or APIFreeLLM).
6. **Posting the Review:** The AI finds issues and generates a summary. PRPilot formats this summary and posts it as a comment back on the GitHub Pull Request.

---

## Project Structure Explanation

Here is a breakdown of the important folders and files in the project, so a newcomer can easily understand where everything lives:

### 1. `api/` (The Entry Point)
This folder contains the serverless endpoints (hosted on Vercel) that interact with the outside world.
- **`webhook.py`**: The heart of the system. This file handles incoming GitHub webhooks. It checks signatures, extracts PR comments, delegates the code to the AI agents, and uses the GitHub API to post the results back.

### 2. `agents/` (The AI Brain)
This folder holds the logic that talks to the Large Language Models (LLMs) and structures the code review.
- **`base.py`**: The base template for reviewing code. It defines how issues (Critical, Warning, Suggestion) are structured and crafts the prompts sent to the LLM.
- **`llm_client.py`**: The smart routing system. It contains the logic to connect to multiple different AI providers (Gemini, Groq, LLMApi, APIFreeLLM). It ensures that if one API key hits a rate limit, the system gracefully shifts to a backup key so the review never fails.

### 3. `dummy_repos/` (For Testing)
- **`prpilot-demo-app/`**: Our designated testing repository. We push intentionally buggy code here to trigger PRPilot and see how well it catches problems like hardcoded passwords or SQL injections.

### 4. Configuration & Setup Files
- **`.env` / `.env.production` / `.env.vercel`**: These files store sensitive access keys securely. They hold API keys for the AI models (Gemini, Grok), GitHub App secrets, and database keys (Supabase).
- **`requirements.txt`**: Lists all the Python packages the system depends on to run successfully (e.g., `fastapi`, `PyGithub`, `google-genai`).
- **`vercel.json`**: Instructions telling Vercel how to build and host the `api/webhook.py` function.

### 5. `test_local.py`
A local testing script. It allows a developer to test the AI review agents on a local file (like `test_samples/sample_code.py`) without having to push code to GitHub. It's the primary way to quickly check if the AI logic is working.

---

## Why This Architecture?
- **Serverless (Vercel)**: We don't need a server running 24/7. Vercel spins up the backend in milliseconds exactly when GitHub sends a webhook, making it highly cost-effective and scalable.
- **Resilient AI Feedback**: By using multiple AI providers (Gemini, Groq, LLMApi, APIFreeLLM) behind a `MultiProviderLLM` manager, PRPilot guarantees that developers always receive feedback even if specific AI APIs are down or rate-limited.
- **Agentic Design**: `base.py` sets up a system where we can easily add new "Specialist Agents" in the future (e.g., an agent purely checking for accessibility issues, or database efficiency).
