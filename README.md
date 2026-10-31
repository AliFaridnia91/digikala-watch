# Digikala watch

Checks a Digikala product every minute (GitHub Actions) and sends a Telegram
message whenever a variant comes in stock that was not on sale at the previous
check. The last seen variants are kept in `state.json`.

Secrets: `TELEGRAM_BOT_TOKEN` (required), `TELEGRAM_CHAT_ID` (optional; defaults
to whoever last messaged the bot). The product is set in
`.github/workflows/watch.yml`. To stop, disable the workflow in the Actions tab.
