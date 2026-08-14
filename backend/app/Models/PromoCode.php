<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Attributes\Fillable;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\HasMany;

#[Fillable(['code', 'amount', 'expires_at'])]
class PromoCode extends Model
{
    protected function casts(): array
    {
        return [
            'amount' => 'decimal:2',
            'expires_at' => 'datetime',
        ];
    }

    public function promoClaims(): HasMany
    {
        return $this->hasMany(PromoClaim::class);
    }
}
