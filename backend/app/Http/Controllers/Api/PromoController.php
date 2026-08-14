<?php

namespace App\Http\Controllers\Api;

use App\Exceptions\PromoClaimException;
use App\Http\Controllers\Controller;
use App\Http\Requests\ClaimPromoCodeRequest;
use App\Http\Requests\PromoClaimHistoryRequest;
use App\Models\Player;
use App\Services\PromoClaimService;
use Illuminate\Http\Request;

class PromoController extends Controller
{
    public function __construct(private readonly PromoClaimService $promoClaimService)
    {
    }

    public function claim(ClaimPromoCodeRequest $request)
    {
        try {
            $player = $this->resolvePlayer($request);
            $claim = $this->promoClaimService->claim($player, $request->validated('code'));
        } catch (PromoClaimException $e) {
            return response()->json(['message' => $e->getMessage()], $e->status);
        }

        return response()->json([
            'claim' => [
                'id' => $claim->id,
                'promo_code' => $claim->promoCode->code,
                'amount' => $claim->amount,
                'status' => $claim->status,
                'created_at' => $claim->created_at,
            ],
            'balance' => $player->fresh()->balance,
        ], 201);
    }

    public function revoke(Request $request, int $claimId)
    {
        try {
            $player = $this->resolvePlayer($request);
            $claim = $this->promoClaimService->revoke($player, $claimId);
        } catch (PromoClaimException $e) {
            return response()->json(['message' => $e->getMessage()], $e->status);
        }

        return response()->json([
            'claim' => [
                'id' => $claim->id,
                'promo_code' => $claim->promoCode->code,
                'amount' => $claim->amount,
                'status' => $claim->status,
                'created_at' => $claim->created_at,
            ],
            'balance' => $player->fresh()->balance,
        ]);
    }

    public function history(PromoClaimHistoryRequest $request)
    {
        try {
            $player = $this->resolvePlayer($request);
        } catch (PromoClaimException $e) {
            return response()->json(['message' => $e->getMessage()], $e->status);
        }

        $query = $player->promoClaims()->with('promoCode:id,code,amount')->latest();

        if ($status = $request->validated('status')) {
            $query->where('status', $status);
        }

        return response()->json(
            $query->paginate($request->validated('per_page', 15))
        );
    }

    /**
     * @throws PromoClaimException
     */
    private function resolvePlayer(Request $request): Player
    {
        $player = $request->user()->player;

        if (! $player) {
            throw new PromoClaimException('No player profile is associated with this account.', 422);
        }

        return $player;
    }
}
