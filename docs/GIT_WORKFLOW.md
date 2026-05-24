# Git Workflow

## Первый commit
```bash
git init
git add .
git commit -m "Initial Galochka 3 Hedra bot"
```

Создай пустой репозиторий на GitHub или GitLab вручную, затем:

```bash
git remote add origin <REAL_REPOSITORY_URL>
git branch -M main
git push -u origin main
```

## Clone на VPS
```bash
git clone <REAL_REPOSITORY_URL> /opt/galochka-hedra-bot
cd /opt/galochka-hedra-bot
cp .env.example .env
nano .env
docker compose up -d --build
```

## Последующие обновления
```bash
git add .
git commit -m "описание изменения"
git push
ssh user@server
cd /opt/galochka-hedra-bot
git pull
docker compose up -d --build
```
