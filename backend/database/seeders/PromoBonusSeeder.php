<?php

namespace Database\Seeders;

use App\Models\Player;
use App\Models\PromoCode;
use Illuminate\Database\Seeder;

class PromoBonusSeeder extends Seeder
{
    /**
     * Run the database seeds.
     */
    public function run(): void
    {
        collect([
            ['name' => 'Alice', 'balance' => 100],
            ['name' => 'Bob', 'balance' => 0],
            ['name' => 'Charlie', 'balance' => 50.5],
        ])->each(fn (array $player) => Player::query()->firstOrCreate(
            ['name' => $player['name']],
            ['balance' => $player['balance']]
        ));

        collect([
            ['code' => 'WELCOME10', 'amount' => 10, 'expires_at' => now()->addMonth()],
            ['code' => 'BONUS50', 'amount' => 50, 'expires_at' => now()->addWeek()],
            ['code' => 'VIP100', 'amount' => 100, 'expires_at' => now()->addDays(3)],
            ['code' => 'EXPIRED5', 'amount' => 5, 'expires_at' => now()->subDay()],
        ])->each(fn (array $promoCode) => PromoCode::query()->firstOrCreate(
            ['code' => $promoCode['code']],
            ['amount' => $promoCode['amount'], 'expires_at' => $promoCode['expires_at']]
        ));
    }
}
