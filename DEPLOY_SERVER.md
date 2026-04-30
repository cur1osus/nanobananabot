# Деплой `nanobananobot` на сервер

## Куда деплоим
- **Сервер:** `root@109.120.184.100`
- **Алиас:** `proj` (в `~/.bashrc` → `alias proj='ssh root@109.120.184.100'`)
- **Папка проекта на сервере:** `/root/nanobananabot`
- **Сервис:** `nanobananabot.service`
- **Image backend:** Runware API `https://api.runware.ai/v1`

## Как деплоить (пошагово)

### 1) Локально: перейти в проект
```bash
cd ~/Desktop/nanobananabot
```

### 2) Залить код на сервер (без перезаписи `.env`)
```bash
rsync -az \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.ruff_cache' \
  --exclude '.mypy_cache' \
  --exclude '.env' \
  ~/Desktop/nanobananabot/ root@109.120.184.100:/root/nanobananabot/
```

### 3) Обновить зависимости на сервере
```bash
proj
cd /root/nanobananabot
.venv/bin/pip install -r r.txt
```

### 4) Перезапустить сервис
```bash
systemctl restart nanobananabot
systemctl is-active nanobananabot
```

Перед рестартом проверьте, что в `/root/nanobananabot/.env` заданы:
- `IMAGE_BACKEND_API_KEY=...` (Runware API key)
- `IMAGE_BACKEND_BASE_URL=https://api.runware.ai/v1` (по умолчанию, можно не задавать)

Для proxy:
- если задан `IMAGE_BACKEND_PROXY_URL`, бот использует именно его;
- если `IMAGE_BACKEND_PROXY_URL` пустой, бот автоматически использует `HTTP_PROXY`, `HTTPS_PROXY` или `ALL_PROXY` из окружения.

Для ограничения зависаний генерации можно настраивать:
- `IMAGE_BACKEND_TOTAL_TIMEOUT` — общий потолок ожидания одного запроса генерации;
- `IMAGE_BACKEND_RATE_LIMIT_RETRIES` и `IMAGE_BACKEND_RATE_LIMIT_BACKOFF` — поведение при `429`.

### 5) Проверить логи
```bash
journalctl -u nanobananabot -n 50 --no-pager
```

Ожидаемо в логах:
- `Бот запущен`
- `Start polling`

---

## Токен бота

После получения нового токена:

1. Открыть `/root/nanobananabot/.env`
2. Обновить значение переменной токена (например, `BOT_TOKEN=...`)
3. Перезапустить сервис:
```bash
systemctl restart nanobananabot
journalctl -u nanobananabot -n 30 --no-pager
```

---

## Что уже сделано сейчас
- Код из `~/Desktop/nanobananabot` задеплоен в `/root/nanobananabot`
- Зависимости проверены (`pip install -r r.txt`)
- Сервис `nanobananabot` перезапущен и работает (`active`, polling запущен)
- Image backend переведён на Runware API `https://api.runware.ai/v1`
- Исправлен runtime-баг импорта `TOPUP_METHODS_TEXT` в `bot/utils/texts.py`
