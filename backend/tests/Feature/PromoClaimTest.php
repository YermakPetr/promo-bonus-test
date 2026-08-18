<?php

namespace Tests\Feature;

use App\Models\Player;
use App\Models\PromoCode;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class PromoClaimTest extends TestCase
{
    use RefreshDatabase;

    public function test_user_can_claim_active_promo_code(): void
    {
        $user = User::factory()->create();

        $player = Player::create([
            'user_id' => $user->id,
            'name' => $user->name,
            'balance' => 0,
        ]);

        $promoCode = PromoCode::create([
            'code' => 'WELCOME10',
            'amount' => 10,
            'expires_at' => now()->addMonth(),
        ]);

        $response = $this
            ->actingAs($user)
            ->postJson('/api/promo/claim', [
                'code' => 'WELCOME10',
            ]);

        $response
            ->assertStatus(201)
            ->assertJsonPath('balance', '10.00');

        $this->assertDatabaseHas('promo_claims', [
            'player_id' => $player->id,
            'promo_code_id' => $promoCode->id,
            'status' => 'applied',
            'amount' => '10.00',
        ]);
    }

    public function test_user_cannot_claim_same_promo_code_twice(): void
    {
        $user = User::factory()->create();

        $player = Player::create([
            'user_id' => $user->id,
            'name' => $user->name,
            'balance' => 0,
        ]);

        PromoCode::create([
            'code' => 'WELCOME10',
            'amount' => 10,
            'expires_at' => now()->addMonth(),
        ]);

        $this->actingAs($user)
            ->postJson('/api/promo/claim', [
                'code' => 'WELCOME10',
            ])
            ->assertStatus(201);

        $response = $this->actingAs($user)
            ->postJson('/api/promo/claim', [
                'code' => 'WELCOME10',
            ]);

        $response
            ->assertStatus(409)
            ->assertJson([
                'message' => 'You have already claimed this promo code.',
            ]);

        $this->assertDatabaseCount('promo_claims', 1);

        $this->assertDatabaseHas('players', [
            'id' => $player->id,
            'balance' => '10.00',
        ]);
    }

    public function test_user_cannot_claim_expired_promo_code(): void
    {
        $user = User::factory()->create();

        $player = Player::create([
            'user_id' => $user->id,
            'name' => $user->name,
            'balance' => 0,
        ]);

        PromoCode::create([
            'code' => 'EXPIRED5',
            'amount' => 5,
            'expires_at' => now()->subDay(),
        ]);

        $response = $this->actingAs($user)
            ->postJson('/api/promo/claim', [
                'code' => 'EXPIRED5',
            ]);

        $response
            ->assertStatus(422)
            ->assertJson([
                'message' => 'This promo code has expired.',
            ]);

        $this->assertDatabaseCount('promo_claims', 0);

        $this->assertDatabaseHas('players', [
            'id' => $player->id,
            'balance' => '0.00',
        ]);
    }

    public function test_user_can_revoke_promo_claim(): void
    {
        $user = User::factory()->create();

        $player = Player::create([
            'user_id' => $user->id,
            'name' => $user->name,
            'balance' => 0,
        ]);

        PromoCode::create([
            'code' => 'WELCOME10',
            'amount' => 10,
            'expires_at' => now()->addMonth(),
        ]);

        $claimResponse = $this->actingAs($user)
            ->postJson('/api/promo/claim', [
                'code' => 'WELCOME10',
            ])
            ->assertStatus(201);

        $claimId = $claimResponse->json('claim.id');

        $this->assertDatabaseHas('players', [
            'id' => $player->id,
            'balance' => '10.00',
        ]);

        $response = $this->actingAs($user)
            ->patchJson("/api/promo/{$claimId}/revoke");

        $response
            ->assertStatus(200)
            ->assertJsonPath('claim.status', 'revoked')
            ->assertJsonPath('balance', '0.00');

        $this->assertDatabaseHas('promo_claims', [
            'id' => $claimId,
            'status' => 'revoked',
        ]);

        $this->assertDatabaseHas('players', [
            'id' => $player->id,
            'balance' => '0.00',
        ]);
    }

    public function test_user_cannot_revoke_another_users_claim(): void
    {
        $user1 = User::factory()->create();

        $player1 = Player::create([
            'user_id' => $user1->id,
            'name' => $user1->name,
            'balance' => 0,
        ]);

        $user2 = User::factory()->create();

        $player2 = Player::create([
            'user_id' => $user2->id,
            'name' => $user2->name,
            'balance' => 0,
        ]);

        PromoCode::create([
            'code' => 'WELCOME10',
            'amount' => 10,
            'expires_at' => now()->addMonth(),
        ]);

        $claimResponse = $this->actingAs($user1)
            ->postJson('/api/promo/claim', [
                'code' => 'WELCOME10',
            ])
            ->assertStatus(201);

        $claimId = $claimResponse->json('claim.id');

        $response = $this->actingAs($user2)
            ->patchJson("/api/promo/{$claimId}/revoke");

        $response
            ->assertStatus(403)
            ->assertJson([
                'message' => 'This promo claim does not belong to you.',
            ]);

        $this->assertDatabaseHas('promo_claims', [
            'id' => $claimId,
            'player_id' => $player1->id,
            'status' => 'applied',
        ]);

        $this->assertDatabaseHas('players', [
            'id' => $player1->id,
            'balance' => '10.00',
        ]);

        $this->assertDatabaseHas('players', [
            'id' => $player2->id,
            'balance' => '0.00',
        ]);
    }
}
