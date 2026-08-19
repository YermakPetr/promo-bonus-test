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

    public static function claimNotFound(): self
    {
        return new self('Promo claim not found.', 404);
    }

    public static function claimNotOwned(): self
    {
        return new self('This promo claim does not belong to you.', 403);
    }

    public static function claimAlreadyRevoked(): self
    {
        return new self('This promo claim has already been revoked.', 409);
    }

    public static function insufficientBalance(): self
    {
        return new self('Insufficient balance to revoke this promo claim.', 409);
    }
}
