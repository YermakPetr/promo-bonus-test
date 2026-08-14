<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    /**
     * Run the migrations.
     */
    public function up(): void
    {
        Schema::create('promo_claims', function (Blueprint $table) {
            $table->id();
            $table->foreignId('player_id')->constrained()->cascadeOnDelete();
            $table->foreignId('promo_code_id')->constrained()->cascadeOnDelete();
            $table->enum('status', ['applied', 'revoked'])->default('applied');
            $table->decimal('amount', 12, 2);
            $table->timestamps();

            $table->unique(['player_id', 'promo_code_id']);
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('promo_claims');
    }
};
