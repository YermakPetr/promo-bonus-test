<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Attributes\Fillable;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\HasMany;

#[Fillable(['name', 'balance'])]
class Player extends Model
{
    protected function casts(): array
    {
        return [
            'balance' => 'decimal:2',
        ];
    }

    public function promoClaims(): HasMany
    {
        return $this->hasMany(PromoClaim::class);
    }
}
