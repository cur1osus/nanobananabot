# NanoBananaBot

Telegram bot scaffold for Nano Banana image editing. Users pick a model, send 1-4 photos, add a prompt, and the bot queues a placeholder generation task.

**Setup**
1. Create a local env file: `cp .env.example .env`
2. Fill in required values in `.env`
3. Run locally with `make dev` or `uv run -m bot`

**Notes**
- In `APP_ENV=dev`, the bot can start without `IMAGE_BACKEND_API_KEY` (warns at startup).
- In non-dev environments, `IMAGE_BACKEND_API_KEY` is required.

**Current Flow**
1. `/start` sends Nano Banana welcome + model chooser.
2. User selects a model and uploads 1-4 photos.
3. Bot requests a text prompt and starts a fake generation task.

**TODOs**
- Integrate real image backend API (replace the fake enqueue in `bot/utils/image_tasks.py`).
- Persist image generation tasks and deliver results back to users.
- Optional: deduct credits per model and add top-up flows.
