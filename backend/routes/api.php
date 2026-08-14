<?php

use App\Http\Controllers\Api\AuthController;
use App\Http\Controllers\Api\PromoController;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Route;

Route::post('/register', [AuthController::class, 'register']);
Route::post('/login', [AuthController::class, 'login']);

Route::middleware('auth:sanctum')->group(function () {
    Route::post('/logout', [AuthController::class, 'logout']);

    Route::get('/user', function (Request $request) {
        return $request->user();
    });

    Route::post('/promo/claim', [PromoController::class, 'claim']);
    Route::get('/promo/history', [PromoController::class, 'history']);
    Route::patch('/promo/{claimId}/revoke', [PromoController::class, 'revoke'])->whereNumber('claimId');
});
