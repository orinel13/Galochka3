# VPS Deploy

Команды рассчитаны на Ubuntu/Debian VPS.

```bash
sudo apt update
sudo apt install -y git curl ca-certificates nano sqlite3
```

## Docker
```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo tee /etc/apt/keyrings/docker.asc >/dev/null
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

## Clone
```bash
sudo mkdir -p /opt/galochka-hedra-bot
sudo chown "$USER":"$USER" /opt/galochka-hedra-bot
git clone <YOUR_REPO_URL> /opt/galochka-hedra-bot
cd /opt/galochka-hedra-bot
cp .env.example .env
nano .env
```

Заполни `BOT_TOKEN`, `HEDRA_API_KEY`, `ADMIN_TELEGRAM_ID`.

## Init and Run
```bash
docker compose run --rm galochka-hedra-bot python scripts/init_db.py
docker compose up -d --build
docker compose logs -f
```

Если Docker Hub вернул `429 Too Many Requests`, проект уже использует public ECR mirror для Python base image. После обновления кода выполни:

```bash
git pull
docker compose build --no-cache
docker compose up -d
```

Альтернатива: выполнить `docker login` на VPS под Docker Hub аккаунтом и повторить build.

## Operations
```bash
docker compose ps
docker compose restart
docker compose down
docker compose logs -f
sqlite3 ./data/galochka.db ".tables"
scripts/backup_db.sh
```

## Update
```bash
cd /opt/galochka-hedra-bot
git pull
docker compose up -d --build
docker compose logs -f
```

## Systemd Alternative
```bash
sudo useradd --system --home /opt/galochka-hedra-bot --shell /usr/sbin/nologin galochka || true
sudo chown -R galochka:galochka /opt/galochka-hedra-bot
cd /opt/galochka-hedra-bot
python3.12 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python scripts/init_db.py
sudo cp systemd/galochka-hedra-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now galochka-hedra-bot
sudo journalctl -u galochka-hedra-bot -f
```
