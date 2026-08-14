# Promo Bonus Test

Monorepo containing a Laravel REST API backend and a Vue 3 (Vite) frontend.

## Structure

- `backend/` — Laravel REST API with token authentication via [Laravel Sanctum](https://laravel.com/docs/sanctum).
- `frontend/` — Vue 3 SPA scaffolded with Vite.

## Backend setup

```bash
cd backend
composer install
cp .env.example .env
php artisan key:generate
touch database/database.sqlite
php artisan migrate
php artisan serve
```

API auth endpoints:

- `POST /api/register` — create a user, returns a Sanctum token
- `POST /api/login` — authenticate, returns a Sanctum token
- `POST /api/logout` — revoke the current token (requires `Authorization: Bearer <token>`)
- `GET /api/user` — get the authenticated user (requires `Authorization: Bearer <token>`)

## Frontend setup

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

The frontend talks to the API via `VITE_API_BASE_URL` (see `frontend/.env.example`), using the token stored in
`localStorage` under the `auth_token` key (`src/services/api.js`).
