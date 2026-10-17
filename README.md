# Eltrona connectivity monitor

Surveille la connectivité Internet **IPv4 et IPv6** indépendamment via HTTPS et prévient sur Telegram au démarrage et après rétablissement confirmé des deux protocoles.

## Démarrage (Linux / Docker)

```sh
cp .env.example .env
# Configurer TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID dans .env
chmod 600 .env
docker compose up -d --build
docker compose logs -f connectivity-monitor
```

Créer un bot avec [@BotFather](https://t.me/BotFather), lui envoyer `/start`, puis récupérer l'identifiant numérique du chat via `getUpdates`. Ne jamais committer `.env` ni afficher le token.

Le moniteur teste les résolveurs HTTPS Cloudflare et Google directement par adresses IPv4/IPv6 (sans dépendre du DNS pour les sondes). Par défaut : contrôle toutes les 60 s, rétablissement après 3 contrôles successifs. L'état est conservé dans le volume Docker. Les notifications Telegram sont tentées via IPv6, même pendant une panne IPv4. Si l'API est inaccessible, l'envoi sera réessayé.

## Sans Docker

Voir `ip-connectivity-monitor.service` comme modèle pour systemd ; adapter les chemins, le compte de service et `STATE_FILE` (ex. `/var/lib/ip-connectivity-monitor/state.json`).

## Tests

```sh
python3 -m unittest discover -s tests -v
```

> Les sondes vérifient une connectivité HTTPS vers deux destinations publiques, pas l'accès à tous les sites. L'envoi Telegram dépend aussi de la disponibilité de son API.
