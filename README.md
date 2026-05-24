# Galochka 3 Hedra Bot

Telegram-бот для команды до 10 пользователей: Hedra TTS, avatar video, voice clone, очередь задач, SQLite-история и Telegram-only администрирование.

Проект Hedra-only: без локального ML, Qwen, CUDA, OpenAI, ElevenLabs и webhook.

## Возможности
- Текст -> аудио через Hedra TTS.
- Текст + фото -> avatar video 1:1.
- Аудио/voice + фото -> avatar video 1:1.
- Текст -> аудио -> кнопка "Сделать видео из этого аудио".
- Admin approval для новых пользователей.
- Голоса: ручной `voice_id`, voice clone, default voice, выбор пользователем.
- Hedra credits, модели, history jobs, TTL cleanup.
- Docker Compose и systemd запуск.

## .env
```bash
cp .env.example .env
nano .env
```

Заполни:
- `BOT_TOKEN`
- `HEDRA_API_KEY`
- `ADMIN_TELEGRAM_ID`

Остальные значения можно оставить по умолчанию.

## Локальный запуск Linux/macOS
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
nano .env
python scripts/init_db.py
python -m app.main
```

## Windows через WSL
Открой проект в WSL, установи Python 3.12 и повтори команды Linux/macOS. Для voice-сообщений нужен `ffmpeg`.

## Docker
```bash
cp .env.example .env
nano .env
docker compose up -d --build
docker compose logs -f
```

Dockerfile использует public ECR mirror для Python base image, чтобы не зависеть от анонимного Docker Hub pull limit. Если сервер всё равно получил `429 Too Many Requests`, выполни `docker login` или повтори build позже.

## Systemd
```bash
sudo cp systemd/galochka-hedra-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now galochka-hedra-bot
sudo journalctl -u galochka-hedra-bot -f
```

## Первый голос
Если Hedra `voice_id` уже есть:
```text
/admin_add_voice Мирослава voice_id
/admin_set_default_voice voice_id
```

## Voice clone
```text
/admin_clone_voice
```
Бот попросит имя и audio sample. Локальный sample удаляется после завершения clone flow.

## Баланс
```text
/balance
/admin_balance
/admin_hedra_test
```

## Текст -> аудио -> видео
1. Нажми `🎙 Текст → аудио`.
2. Отправь текст.
3. После готового аудио нажми `🖼 Сделать видео из этого аудио`.
4. Отправь фото.
5. Бот поставит video job в очередь.

## Git workflow
```bash
git init
git add .
git commit -m "Initial Galochka 3 Hedra bot"
git branch -M main
git remote add origin <YOUR_REPO_URL>
git push -u origin main
```

## Обновление на VPS
```bash
cd /opt/galochka-hedra-bot
git pull
docker compose up -d --build
docker compose logs -f
```

## Backup SQLite
```bash
scripts/backup_db.sh
scripts/restore_db.sh ./data/backups/galochka_YYYYMMDDHHMMSS.db
```

## Основные команды
User: `/start`, `/voices`, `/setvoice`, `/balance`, `/help`.

Admin: `/admin`, `/admin_users`, `/admin_allow`, `/admin_deny`, `/admin_revoke`, `/admin_voices`, `/admin_add_voice`, `/admin_clone_voice`, `/admin_models_sync`, `/admin_models`, `/admin_set_video_model`, `/admin_balance`, `/admin_jobs`, `/admin_job`, `/admin_cancel_job`, `/admin_cleanup`, `/admin_export_db`, `/admin_hedra_test`.
