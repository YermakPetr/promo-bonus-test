<?php

namespace Tests\Feature;

use App\Models\Player;
use App\Models\PromoCode;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;
use App\Models\PromoClaim;

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

    public function test_user_cannot_revoke_promo_claim_with_insufficient_balance(): void
    {
        $user = User::factory()->create();

        $player = Player::create([
            'user_id' => $user->id,
            'name' => $user->name,
            'balance' => 5,
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
            'balance' => '15.00',
        ]);

        $player->decrement('balance', 10);

        $response = $this->actingAs($user)
            ->patchJson("/api/promo/{$claimId}/revoke");

        $response
            ->assertStatus(409)
            ->assertJson([
                'message' => 'Insufficient balance to revoke this promo claim.',
            ]);

        $this->assertDatabaseHas('promo_claims', [
            'id' => $claimId,
            'status' => 'applied',
        ]);

        $this->assertDatabaseHas('players', [
            'id' => $player->id,
            'balance' => '5.00',
        ]);
    }

    public function test_user_cannot_revoke_already_revoked_promo_claim(): void
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

        $this->actingAs($user)
            ->patchJson("/api/promo/{$claimId}/revoke")
            ->assertStatus(200);

        $this->assertDatabaseHas('players', [
            'id' => $player->id,
            'balance' => '0.00',
        ]);

        $response = $this->actingAs($user)
            ->patchJson("/api/promo/{$claimId}/revoke");

        $response
            ->assertStatus(409)
            ->assertJson([
                'message' => 'This promo claim has already been revoked.',
            ]);

        $this->assertDatabaseHas('promo_claims', [
            'id' => $claimId,
            'status' => 'revoked',
        ]);

        $this->assertDatabaseHas('players', [
            'id' => $player->id,
            'balance' => '0.00',
        ]);
    }

    public function test_guest_cannot_claim_promo_code(): void
    {
        PromoCode::create([
            'code' => 'WELCOME10',
            'amount' => 10,
            'expires_at' => now()->addMonth(),
        ]);

        $response = $this->postJson('/api/promo/claim', [
            'code' => 'WELCOME10',
        ]);

        $response->assertStatus(401);

        $this->assertDatabaseCount('promo_claims', 0);
    }

    public function test_guest_cannot_revoke_promo_claim(): void
    {
        $user = User::factory()->create();

        $player = Player::create([
            'user_id' => $user->id,
            'name' => $user->name,
            'balance' => 10,
        ]);

        $promoCode = PromoCode::create([
            'code' => 'WELCOME10',
            'amount' => 10,
            'expires_at' => now()->addMonth(),
        ]);

        $claim = \App\Models\PromoClaim::create([
            'player_id' => $player->id,
            'promo_code_id' => $promoCode->id,
            'status' => 'applied',
            'amount' => 10,
        ]);

        $response = $this->patchJson("/api/promo/{$claim->id}/revoke");

        $response->assertStatus(401);

        $this->assertDatabaseHas('promo_claims', [
            'id' => $claim->id,
            'status' => 'applied',
        ]);

        $this->assertDatabaseHas('players', [
            'id' => $player->id,
            'balance' => '10.00',
        ]);
    }

    public function test_user_can_only_see_their_own_promo_history(): void
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

        PromoCode::create([
            'code' => 'BONUS50',
            'amount' => 50,
            'expires_at' => now()->addMonth(),
        ]);

        $this->actingAs($user1)
            ->postJson('/api/promo/claim', [
                'code' => 'WELCOME10',
            ])
            ->assertStatus(201);

        $this->actingAs($user2)
            ->postJson('/api/promo/claim', [
                'code' => 'BONUS50',
            ])
            ->assertStatus(201);

        $response = $this->actingAs($user1)
            ->getJson('/api/promo/history');

        $response
            ->assertStatus(200)
            ->assertJsonCount(1, 'data')
            ->assertJsonPath('data.0.promo_code.code', 'WELCOME10')
            ->assertJsonMissing([
                'code' => 'BONUS50',
            ]);
    }

    public function test_database_prevents_duplicate_promo_claims(): void
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

        PromoClaim::create([
            'player_id' => $player->id,
            'promo_code_id' => $promoCode->id,
            'status' => 'applied',
            'amount' => 10,
        ]);

        try {
            PromoClaim::create([
                'player_id' => $player->id,
                'promo_code_id' => $promoCode->id,
                'status' => 'applied',
                'amount' => 10,
            ]);

            $this->fail('Database allowed a duplicate promo claim.');
        } catch (\Throwable $e) {
            $this->assertStringContainsString(
                'UNIQUE',
                strtoupper($e->getMessage())
            );
        }

        $this->assertDatabaseCount('promo_claims', 1);
    }

    public function test_user_cannot_claim_nonexistent_promo_code(): void
    {
        $user = User::factory()->create();

        $player = Player::create([
            'user_id' => $user->id,
            'name' => $user->name,
            'balance' => 0,
        ]);

        $response = $this->actingAs($user)
            ->postJson('/api/promo/claim', [
                'code' => 'NOTFOUND',
            ]);

        $response
            ->assertStatus(404)
            ->assertJson([
                'message' => 'Promo code not found.',
            ]);

        $this->assertDatabaseCount('promo_claims', 0);

        $this->assertDatabaseHas('players', [
            'id' => $player->id,
            'balance' => '0.00',
        ]);
    }

    public function test_user_cannot_claim_promo_without_code(): void
    {
        $user = User::factory()->create();

        $player = Player::create([
            'user_id' => $user->id,
            'name' => $user->name,
            'balance' => 0,
        ]);

        $response = $this->actingAs($user)
            ->postJson('/api/promo/claim', []);

        $response
            ->assertStatus(422)
            ->assertJsonValidationErrors(['code']);

        $this->assertDatabaseCount('promo_claims', 0);

        $this->assertDatabaseHas('players', [
            'id' => $player->id,
            'balance' => '0.00',
        ]);
    }

    public function test_user_cannot_claim_invalid_promo_code(): void
    {
        $user = User::factory()->create();

        $player = Player::create([
            'user_id' => $user->id,
            'name' => $user->name,
            'balance' => 0,
        ]);

        $invalidCodes = [
            'ABC',
            'ABCDEFGHIJKLM',
            'ABC@123',
        ];

        foreach ($invalidCodes as $code) {
            $response = $this->actingAs($user)
                ->postJson('/api/promo/claim', [
                    'code' => $code,
                ]);

            $response->assertStatus(422);
        }

        $this->assertDatabaseCount('promo_claims', 0);

        $this->assertDatabaseHas('players', [
            'id' => $player->id,
            'balance' => '0.00',
        ]);
    }

    public function test_promo_code_accepts_minimum_and_maximum_length(): void
    {
        $user = User::factory()->create();

        $player = Player::create([
            'user_id' => $user->id,
            'name' => $user->name,
            'balance' => 0,
        ]);

        PromoCode::create([
            'code' => 'ABCDEF',
            'amount' => 10,
            'expires_at' => now()->addMonth(),
        ]);

        PromoCode::create([
            'code' => 'ABCDEFGHIJKL',
            'amount' => 20,
            'expires_at' => now()->addMonth(),
        ]);

        $this->actingAs($user)
            ->postJson('/api/promo/claim', [
                'code' => 'ABCDEF',
            ])
            ->assertStatus(201);

        $this->actingAs($user)
            ->postJson('/api/promo/claim', [
                'code' => 'ABCDEFGHIJKL',
            ])
            ->assertStatus(201);

        $this->assertDatabaseHas('players', [
            'id' => $player->id,
            'balance' => '30.00',
        ]);

        $this->assertDatabaseCount('promo_claims', 2);
    }
}
