<?php

namespace App\Exceptions;

use Exception;

class PromoClaimException extends Exception
{
    public function __construct(string $message, public readonly int $status)
    {
        parent::__construct($message);
    }

    public static function codeNotFound(): self
    {
        return new self('Promo code not found.', 404);
    }

    public static function codeExpired(): self
    {
        return new self('This promo code has expired.', 422);
    }

    public static function alreadyClaimed(): self
    {
        return new self('You have already claimed this promo code.', 409);
    }
}
