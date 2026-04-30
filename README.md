# NanoBananaBot

Telegram bot for Nano Banana image editing. Users pick a model, send 1-4 photos, add a prompt, and the bot generates the result through Runware AI.

Image backend is configured via Runware API (`https://api.runware.ai/v1`) and a Runware API key.

**Setup**
1. Create a local env file: `cp .env.example .env`
2. Fill in required values in `.env`
   Required image backend values:
   - `IMAGE_BACKEND_API_KEY=...` (Runware API key)
   - `IMAGE_BACKEND_BASE_URL=https://api.runware.ai/v1` (default, can be omitted)
   Optional reliability values:
   - `IMAGE_BACKEND_TOTAL_TIMEOUT=150`
   - `IMAGE_BACKEND_RATE_LIMIT_RETRIES=1`
   - `IMAGE_BACKEND_RATE_LIMIT_BACKOFF=5`
   Proxy behavior:
   - `IMAGE_BACKEND_PROXY_URL` has priority when set.
   - Otherwise the bot uses standard `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` from environment.
3. Run locally with `make dev` or `uv run -m bot`

**Current Flow**
1. `/start` sends Nano Banana welcome + model chooser.
2. User selects a model (Nano Banana / Nano Banana Pro / Nano Banana 2) and uploads 1-4 photos.
3. Bot requests a text prompt and runs real image generation.

**Models**
- `google:4@1` — Nano Banana (fast, affordable)
- `google:4@2` — Nano Banana Pro (best quality, slower)
- `google:4@3` — Nano Banana 2 (better detail, thinking support)

**Notes**
- Image generation is synchronous from the bot process.
- Production deploy uses Runware API endpoint and a Runware API key from `.env`.
- Image generation has a bounded total wait time to avoid blocking user requests indefinitely.
