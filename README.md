# Digikala watch

Checks a Digikala product every minute (GitHub Actions) and sends a Telegram
message when a matching variant is in stock, then turns itself off.

Secrets: `TELEGRAM_BOT_TOKEN` (required), `TELEGRAM_CHAT_ID` (optional; defaults
to whoever last messaged the bot). Product and variant are set in
`.github/workflows/watch.yml`. To watch again, re-enable the workflow in the
Actions tab.
