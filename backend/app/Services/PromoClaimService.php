<?php

namespace App\Services;

use App\Exceptions\PromoClaimException;
use App\Models\Player;
use App\Models\PromoClaim;
use App\Models\PromoCode;
use Illuminate\Database\UniqueConstraintViolationException;
use Illuminate\Support\Facades\DB;

class PromoClaimService
{
    /**
     * Apply a promo code to a player, crediting their balance.
     *
     * @throws PromoClaimException
     */
    public function claim(Player $player, string $code): PromoClaim
    {
        $promoCode = PromoCode::where('code', $code)->first();

        if (! $promoCode) {
            throw PromoClaimException::codeNotFound();
        }

        if ($promoCode->expires_at !== null && $promoCode->expires_at->isPast()) {
            throw PromoClaimException::codeExpired();
        }

        $alreadyClaimed = PromoClaim::where('player_id', $player->id)
            ->where('promo_code_id', $promoCode->id)
            ->exists();

        if ($alreadyClaimed) {
            throw PromoClaimException::alreadyClaimed();
        }

        return DB::transaction(function () use ($player, $promoCode) {
            try {
                $claim = PromoClaim::create([
                    'player_id' => $player->id,
                    'promo_code_id' => $promoCode->id,
                    'status' => 'applied',
                    'amount' => $promoCode->amount,
                ]);
            } catch (UniqueConstraintViolationException) {
                // The DB-level unique index is the final guard against a
                // duplicate claim slipping through a race condition.
                throw PromoClaimException::alreadyClaimed();
            }

            $player->increment('balance', $promoCode->amount);

            return $claim;
        });
    }
}
