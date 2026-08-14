#!/bin/sh
set -e

if [ ! -f .env ]; then
    cp .env.example .env
fi

if ! grep -q "^APP_KEY=base64:" .env; then
    php artisan key:generate --force
fi

if [ ! -s database/database.sqlite ]; then
    touch database/database.sqlite
    php artisan migrate --force --seed
fi

exec "$@"
