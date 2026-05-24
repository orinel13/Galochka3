# Hedra Notes

Base URL: `https://api.hedra.com/web-app/public`

Auth header: `X-API-Key`.

Используемые endpoints:
- `GET /voices`
- `GET /models`
- `POST /assets`
- `POST /assets/{id}/upload`
- `POST /generations`
- `GET /generations/{generation_id}/status`
- `GET /billing/credits`

Бот не полагается на один hardcoded model id. Сначала выполни:

```text
/admin_models_sync
/admin_models
/admin_set_video_model <model_id>
```

Если модель не выбрана, бот пытается выбрать video/avatar model с поддержкой `1:1`. Если подходящая модель не найдена, video generation не запускается.

## Models
Все модели берутся из `GET /models` и сохраняются в `hedra_models.raw_json`.

Имена `Nano Banana Pro`, `Grok Imagine`, `Kling V3 Standard`, `Sora 2 Pro`, `Hedra Omnia`, `Hedra Character 3` считаются preferred names, а не гарантированными API identifiers.

Если модель видна в web UI, но не приходит через `/models`, бот не может использовать её официально. Browser automation, Playwright и парсинг Hedra Studio запрещены и не используются.

## Prompts
Для video/avatar prompt передаётся через:

```json
{
  "generated_video_inputs": {
    "text_prompt": "..."
  }
}
```

`text_prompt` отправляется только если он не пустой. Для image-to-video без prompt бот может повторить запрос с fallback prompt, если API потребовал prompt.

## Video duration
Некоторые I2V модели, включая Grok Video I2V, требуют `generated_video_inputs.duration_ms`.

Бот хранит пользовательскую длительность в `user_settings.video_duration_ms`, а фактическую использованную длительность в `jobs.duration_ms`. Если Hedra возвращает 422 с `duration_ms is required` или `Valid values: [...]`, бот парсит допустимые значения, выбирает ближайшее к пользовательскому значению и повторяет запрос один раз.

## Image
Text-to-image использует:

```json
{
  "type": "image",
  "text_prompt": "...",
  "ai_model_id": "...",
  "aspect_ratio": "1:1",
  "resolution": "1080p",
  "batch_size": 1,
  "enhance_prompt": false
}
```

Image edit включается только если `/models` показывает признаки reference image/image edit input для выбранной модели. Иначе бот сообщает, что режим доступен в web UI, но не в текущем public API.

Для image edit / I2I используется adapter layer:
- text-to-image не смешивается с image edit;
- входное изображение загружается как Hedra image asset;
- adapter передаёт загруженный asset через `reference_image_ids` для I2I-моделей;
- если модель явно требует URL, adapter дополнительно пытается получить usable image URL/reference image;
- если модель требует image URL, но public API не отдаёт URL, бот не делает fake success и завершает job понятной ошибкой.

Grok Imagine I2I запускается как `type="image_to_image"` с `reference_image_ids: ["<uploaded_asset_id>"]`. Это не то же самое, что локальный путь, Telegram `file_id` или произвольный URL.

## Почему модель есть в web UI Hedra, но может не работать в API
Бот работает только через официальный Hedra API:
- модели берутся из `GET /models`;
- генерации запускаются через `POST /generations`;
- payload зависит от модели и её `raw_json`;
- browser automation, Playwright и парсинг Hedra Studio не используются.

Если модель видна в web UI, но не приходит через `/models`, или API не отдаёт совместимый способ передачи reference image, бот не может использовать эту модель официально.

## Навигация
В пользовательском UI есть `⬅️ Назад` и `🏠 Меню`.

`⬅️ Назад` очищает текущий ввод и возвращает на предыдущий экран. `🏠 Меню` очищает flow и возвращает в главное меню.
