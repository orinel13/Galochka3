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
