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
