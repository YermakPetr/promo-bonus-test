# Promo Bonus Test

Monorepo containing a Laravel REST API backend and a Vue 3 (Vite) frontend.

## Tech Stack

- PHP 8.4
- Laravel
- Laravel Sanctum
- SQLite
- Vue 3
- Vite
- Axios
- PHPUnit

## Project Structure

- `backend/` - Laravel REST API
- `frontend/` - Vue 3 SPA

## Backend Setup

```bash
cd backend
composer install
cp .env.example .env
php artisan key:generate
php artisan migrate --seed
php artisan serve
```

The API will be available at:

`http://127.0.0.1:8000`

## Frontend Setup

Open a second terminal:

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

The frontend will be available at:

`http://localhost:5173`

The frontend uses `VITE_API_BASE_URL` to configure the API URL.

## Authentication

Authentication is implemented with Laravel Sanctum personal access tokens.

### Register

`POST /api/register`

### Login

`POST /api/login`

### Logout

`POST /api/logout`

Requires:

`Authorization: Bearer <token>`

### Current User

`GET /api/user`

Requires authentication.

## Promo API

### Claim Promo Code

`POST /api/promo/claim`

Example:

```json
{
  "code": "WELCOME10"
}
```

### Claim History

`GET /api/promo/history`

Optional parameters:

- `page`
- `per_page`
- `status`

Supported statuses:

- `applied`
- `revoked`

### Revoke Promo Claim

`PATCH /api/promo/{claimId}/revoke`

Requires authentication.

A user can only revoke their own promo claims.

## Demo Promo Codes

The database seeder creates the following promo codes:

| Code | Amount | Status |
|---|---:|---|
| `WELCOME10` | 10 | Active |
| `BONUS50` | 50 | Active |
| `VIP100` | 100 | Active |
| `EXPIRED5` | 5 | Expired |

## Tests

Run the backend test suite:

```bash
cd backend
php artisan test
```

The test suite covers:

- claiming an active promo code;
- preventing duplicate claims;
- preventing expired promo claims;
- revoking a promo claim;
- preventing users from revoking another user's claim.

## Business Rules

- A promo code can only be claimed once by the same player.
- Expired promo codes cannot be claimed.
- Claiming a promo increases the player's balance.
- Revoking a claim decreases the player's balance.
- A user cannot revoke another user's claim.
- Promo claim creation and balance updates are performed inside a database transaction.
- A database unique constraint prevents duplicate claims.