# Grok Web To API 🚀

> Reverse-engineered REST API for [grok.com](https://grok.com). Drop-in OpenAI-compatible
> endpoint that runs on your browser cookies — no xAI API key required.

Python port of the popular [ntthanh2603/gemini-web-to-api](https://github.com/ntthanh2603/gemini-web-to-api)
pattern, this time wrapping Grok's web client. Built with **FastAPI + httpx** so
streaming is async-native and the dependency surface stays small.

It is **not affiliated with or endorsed by xAI**, and may violate xAI's
Terms of Service. Use at your own risk.

## ✨ Features

- 🍰 **OpenAI-compatible** — `POST /v1/chat/completions` works with any OpenAI client/SDK.
- 🌊 **Streaming** — real SSE chunks (`text/event-stream`) in OpenAI's wire format.
- 🛡️ **Cookie-based auth** — uses your browser SSO cookies; no API keys.
- 🪶 **Pure Python** — `pip install -r requirements.txt`, no compilers.
- 📊 **Per-IP rate limiting** — fixed window, configurable.
- 🔌 **Health probe** — `GET /health` reports auth state.
- 🐳 **Docker-ready** — slim `python:3.11-slim` base, ~150 MB image.

## 🚀 Quick start (Docker)

```bash
git clone https://github.com/yourusername/grok-web-to-api.git
cd grok-web-to-api
cp .env.example .env
# ... fill in .env (see below) ...
docker compose up -d --build
curl http://localhost:4982/health
```

## 🛠️ Quick start (from source)

```bash
pip install -r requirements.txt
cp .env.example .env
# ... fill in .env ...
python main.py
# or:
uvicorn main:app --host 0.0.0.0 --port 4982
```

## 🔑 Get your cookies and challenge values

> **Keep these values secret.** They give anyone with them full access to your xAI account quota.

### Option A: One-click wizard (recommended) ⭐

The new `scripts/extract-everything.py` opens a stealth browser, walks you through sign-in, captures the cookies, decodes the challenge, and writes `.env` automatically. It even runs a smoke test at the end.

```bash
# One-time install of the stealth browser
./scripts/install-cloakbrowser.sh

# Run the wizard — it opens a browser, you sign in, .env gets written
python3 scripts/extract-everything.py
```

What the wizard does:
1. Launches CloakBrowser (stealth Chromium) so Cloudflare treats you as a real user
2. Polls the browser's cookies every 2s — once `sso` + `sso-rw` + `cf_clearance` all appear, it knows you're signed in
3. Sends a throwaway "ping" message to capture the `x-statsig-id` header
4. Decodes the 70-byte header into `CHALLENGE_HEADER_HEX` (49 bytes) + `CHALLENGE_TRAILER` (1 byte)
5. Atomically writes `.env` with `chmod 600`
6. Runs a smoke test (start server, hit `/health`, kill server)

CLI options:
```
--env-file PATH    Where to write .env (default: .env)
--no-smoke         Skip the smoke test
--login-timeout S  Seconds to wait for login (default: 600)
--challenge-timeout S  Seconds to wait for x-statsig-id (default: 60)
--test             Run without a browser (for CI / dry-run)
```

The wizard handles every edge case we hit while building this:
- `cf_clearance` missing → blocks until it appears
- `x-statsig-id` not captured within timeout → clear error message
- User cancels with Ctrl-C → clean exit, no .env written
- Any uncaught exception → exception type in the error output

### Option B: Manual extraction (works on a headless server)

If you're on a server without a display and don't want to use the wizard:

1. **Grab the SSO cookies** in a real desktop browser:
   - Open https://grok.com and sign in.
   - Open DevTools (`F12`) → **Application** → **Cookies** → `https://grok.com`.
   - Copy the **Value** of `sso` → `GROK_SSO_COOKIE`
   - Copy the **Value** of `sso-rw` → `GROK_SSO_RW_COOKIE`
   - Copy the **Value** of `cf_clearance` → `GROK_CF_CLEARANCE` (required!)
   - Copy the **Value** of `__cf_bm` → `GROK_CF_BM` (optional, helps)

2. **Extract the anti-bot challenge** with the same browser:
   - Open DevTools → **Console**
   - Paste the contents of [`scripts/extract-challenge.js`](scripts/extract-challenge.js)
   - Press Enter; the script prints:
     ```
     CHALLENGE_HEADER_HEX=<98 hex chars>
     CHALLENGE_SUFFIX=<string>
     CHALLENGE_TRAILER=<digit 0-9>
     ```
   - Copy all three into `.env`
   - Re-run whenever Grok ships a new web build (the challenge rotates)

3. **Fill the rest of `.env`** (defaults are fine for most users):
   ```
   PORT=4982
   GROK_TEMPORARY=true
   RATE_LIMIT_ENABLED=true
   RATE_LIMIT_WINDOW_SECONDS=60
   RATE_LIMIT_MAX_REQUESTS=20
   ```

4. **Run the server**
   ```bash
   docker compose up -d --build
   # or, without Docker:
   python main.py
   ```

## ✅ Test it

```bash
# health probe
curl http://localhost:4982/health

# list models
curl http://localhost:4982/v1/models

# chat completion (non-streaming)
curl -X POST http://localhost:4982/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-auto",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'

# chat completion (streaming)
curl -N -X POST http://localhost:4982/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-auto",
    "stream": true,
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

Or run the bundled smoke test:

```bash
./test-api.sh
```

And the Python unit tests:

```bash
pip install -r requirements.txt pytest pytest-asyncio respx
pytest -v
```

## 🔌 Use with OpenCode / OpenAI clients

Point any OpenAI-compatible client at this server. The `Authorization`
header is required by most SDKs but its value can be anything — the real
authentication is in the server's `.env`.

```bash
# opencode-style config
export OPENAI_API_BASE=http://localhost:4982/v1
export OPENAI_API_KEY=any-non-empty-string
```

In the OpenCode TUI:
1. Run `opencode` in your terminal.
2. Open the config (`~/.config/opencode/opencode.jsonc`).
3. Set:
   ```json
   {
     "$schema": "https://opencode.ai/config.json",
     "provider": {
       "grok": {
         "npm": "@ai-sdk/openai-compatible",
         "baseURL": "http://localhost:4982/v1",
         "apiKey": "grok-local"
       }
     }
   }
   ```
4. Save and start a session. `grok-auto` will appear in the model picker.

## 📡 API endpoints

| Method | Path                       | Notes                                    |
| ------ | -------------------------- | ---------------------------------------- |
| GET    | `/health`                  | Auth + upstream probe                    |
| GET    | `/`                        | Server identity / endpoint index         |
| GET    | `/v1/models`               | OpenAI-style model list                  |
| GET    | `/v1/models/:id`           | Single model detail                      |
| POST   | `/v1/chat/completions`     | Chat (streaming + non-streaming)         |
| POST   | `/v1/completions`          | Legacy single-prompt; converted to chat  |

### Supported models

| ID            | Maps to                            |
| ------------- | ---------------------------------- |
| `grok-auto`   | Grok picks the best model          |
| `grok-4`      | Grok 4                             |
| `grok-4-fast` | Grok 4 Fast                        |
| `grok-3`      | Grok 3                             |
| `grok-3-mini` | Grok 3 Mini                        |
| `grok-2`      | Grok 2 (may be retired upstream)   |
| `grok-2-mini` | Grok 2 Mini                        |

Unknown model IDs fall back to `grok-auto` with a warning.

## ⚙️ Environment variables

| Var                              | Required | Default      | Description                                      |
| -------------------------------- | -------- | ------------ | ------------------------------------------------ |
| `GROK_SSO_COOKIE`                | yes      | —            | `sso` cookie value from grok.com                 |
| `GROK_SSO_RW_COOKIE`             | yes      | —            | `sso-rw` cookie value from grok.com              |
| `CHALLENGE_HEADER_HEX`           | yes      | —            | 49-byte fingerprint, hex-encoded                 |
| `CHALLENGE_TRAILER`              | no       | `3`          | Single-byte trailer constant                     |
| `PORT`                           | no       | `4982`       | Server port                                      |
| `HOST`                           | no       | `0.0.0.0`    | Bind address                                     |
| `LOG_LEVEL`                      | no       | `INFO`       | `DEBUG`/`INFO`/`WARNING`/`ERROR`                |
| `GROK_TEMPORARY`                 | no       | `true`       | Use Grok's "temporary" (no history) mode         |
| `RATE_LIMIT_ENABLED`             | no       | `true`       | Enable per-IP rate limiting                      |
| `RATE_LIMIT_WINDOW_SECONDS`      | no       | `60`         | Window in seconds                                |
| `RATE_LIMIT_MAX_REQUESTS`        | no       | `20`         | Max requests per IP per window                   |
| `GROK_BASE_URL`                  | no       | grok.com     | Override the upstream base URL                   |
| `GROK_ORIGIN`                    | no       | grok.com     | `Origin` header value                            |
| `GROK_USER_AGENT`                | no       | Chrome 131   | `User-Agent` header value                        |

## 🏗️ Architecture

```
┌────────────────────┐    POST /v1/chat/completions    ┌─────────────────────┐
│  OpenAI client     │ ───────────────────────────────▶│  grok-web-to-api    │
│ (opencode, langchain│                                │  (FastAPI server)   │
│  openai-python, …) │ ◀── SSE /v1/chat completion ───│                     │
└────────────────────┘                                 └──────────┬──────────┘
                                                                   │
                                                                   │  HTTPS + SSO cookies
                                                                   │  + x-statsig-id
                                                                   ▼
                                                         ┌─────────────────────┐
                                                         │  grok.com web API   │
                                                         │  /rest/app-chat/... │
                                                         └─────────────────────┘
```

- `grok_web_to_api/challenge.py` — rebuilds the per-request `x-statsig-id` header cryptographically.
- `grok_web_to_api/client.py` — async httpx client that streams NDJSON/SSE from grok.com.
- `grok_web_to_api/routes.py` — OpenAI ↔ Grok wire-format translation.
- `grok_web_to_api/rate_limit.py` — per-IP fixed-window token bucket.

## 🛡️ Security

- **Never** commit your `.env` file. Add it to `.gitignore`.
- Run the server behind a reverse proxy if you expose it to the internet —
  the rate limiter is in-process and does not synchronize across replicas.
- Cookies grant access to **your** xAI quota. Treat them like passwords.
- This server does not log message contents, but it does log request paths
  and source IPs.

## 🩺 Troubleshooting

| Symptom                                          | Likely cause                                                         |
| ------------------------------------------------ | -------------------------------------------------------------------- |
| `health` returns 503 with "missing …"            | One or more of `GROK_SSO_COOKIE` / `GROK_SSO_RW_COOKIE` / `CHALLENGE_HEADER_HEX` is empty. |
| `health` returns 503 with "auth rejected"        | Cookies are expired or wrong account. Re-grab from DevTools.         |
| Chat returns 502                                  | Grok's web build changed. Re-run `scripts/extract-challenge.js`.     |
| All requests 401 from grok.com                   | `x-statsig-id` is wrong. Check `CHALLENGE_HEADER_HEX` and `CHALLENGE_TRAILER`. |
| Streaming hangs and never completes              | You hit a non-streaming endpoint. `/v1/chat/completions` is the only one that streams. |

## 📦 Project layout

```
grok-web-to-api/
├── grok_web_to_api/
│   ├── __init__.py
│   ├── challenge.py        # x-statsig-id signer
│   ├── client.py           # async httpx client for grok.com
│   ├── config.py           # pydantic-settings + .env loading
│   ├── models.py           # OpenAI wire types
│   ├── rate_limit.py       # per-IP fixed window
│   ├── routes.py           # FastAPI endpoints
│   └── server.py           # app factory + lifespan
├── tests/
│   ├── test_challenge.py
│   ├── test_models.py
│   ├── test_rate_limit.py
│   └── test_routes.py
├── scripts/
│   └── extract-challenge.js
├── main.py                 # entry point
├── test-api.sh             # smoke tests
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── requirements.txt
├── README.md
└── LICENSE
```

## 📜 License

MIT — see [LICENSE](LICENSE).

## ⚠️ Disclaimer

This project reverse-engineers xAI's web API. It is not affiliated with
or endorsed by xAI. Use of this project may violate xAI's Terms of
Service. The authors are not responsible for any account actions xAI
may take as a result.