<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Support\Facades\DB;

return new class extends Migration
{
    public function up(): void
    {
        DB::statement('
            CREATE TRIGGER players_balance_non_negative_insert
            BEFORE INSERT ON players
            FOR EACH ROW
            WHEN NEW.balance < 0
            BEGIN
                SELECT RAISE(ABORT, "Player balance cannot be negative");
            END
        ');

        DB::statement('
            CREATE TRIGGER players_balance_non_negative_update
            BEFORE UPDATE OF balance ON players
            FOR EACH ROW
            WHEN NEW.balance < 0
            BEGIN
                SELECT RAISE(ABORT, "Player balance cannot be negative");
            END
        ');
    }

    public function down(): void
    {
        DB::statement('
            DROP TRIGGER IF EXISTS players_balance_non_negative_insert
        ');

        DB::statement('
            DROP TRIGGER IF EXISTS players_balance_non_negative_update
        ');
    }
};
