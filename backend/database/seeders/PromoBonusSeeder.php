<?php

namespace Database\Seeders;

use App\Models\Player;
use App\Models\PromoCode;
use App\Models\User;
use Illuminate\Database\Seeder;
use Illuminate\Support\Facades\Hash;

class PromoBonusSeeder extends Seeder
{
    /**
     * Run the database seeds.
     */
    public function run(): void
    {
        collect([
            [
                'name' => 'Alice',
                'email' => 'alice@example.com',
                'balance' => 100,
            ],
            [
                'name' => 'Bob',
                'email' => 'bob@example.com',
                'balance' => 0,
            ],
            [
                'name' => 'Charlie',
                'email' => 'charlie@example.com',
                'balance' => 50.50,
            ],
        ])->each(function (array $data): void {
            $user = User::query()->firstOrCreate(
                ['email' => $data['email']],
                [
                    'name' => $data['name'],
                    'password' => Hash::make('password'),
                ]
            );

            Player::query()->firstOrCreate(
                ['user_id' => $user->id],
                [
                    'name' => $data['name'],
                    'balance' => $data['balance'],
                ]
            );
        });

        collect([
            [
                'code' => 'WELCOME10',
                'amount' => 10,
                'expires_at' => now()->addMonth(),
            ],
            [
                'code' => 'BONUS50',
                'amount' => 50,
                'expires_at' => now()->addWeek(),
            ],
            [
                'code' => 'VIP100',
                'amount' => 100,
                'expires_at' => now()->addDays(3),
            ],
            [
                'code' => 'EXPIRED5',
                'amount' => 5,
                'expires_at' => now()->subDay(),
            ],
        ])->each(fn(array $promoCode) => PromoCode::query()->firstOrCreate(
            ['code' => $promoCode['code']],
            [
                'amount' => $promoCode['amount'],
                'expires_at' => $promoCode['expires_at'],
            ]
        ));
    }
}
