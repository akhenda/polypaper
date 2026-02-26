-- Migration: Fix strategy_state uniqueness for Phase 2.1.1
-- Run this on existing databases to update the schema

BEGIN;

-- Drop the old unique constraint if it exists
DO $$
DECLARE
    constraint_name text;
BEGIN
    SELECT conname INTO constraint_name
    FROM pg_constraint
    WHERE conrelid = 'strategy_state'::regclass
      AND conname LIKE 'strategy_state_account_id_strategy_id_key';
    
    IF constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE strategy_state DROP CONSTRAINT %s', constraint_name);
        RAISE NOTICE 'Dropped constraint: %', constraint_name;
    END IF;
END $$;

-- Make strategy_instance_id NOT NULL (if it isn't already)
-- First, backfill any NULL values with corresponding instance IDs
UPDATE strategy_state ss
SET strategy_instance_id = si.id
FROM strategy_instances si
WHERE ss.account_id = si.account_id 
  AND ss.strategy_id = si.strategy_id
  AND ss.strategy_instance_id IS NULL;

-- Now alter the column
ALTER TABLE strategy_state ALTER COLUMN strategy_instance_id SET NOT NULL;

-- Ensure the unique constraint exists on strategy_instance_id
DO $$
DECLARE
    constraint_exists boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'strategy_state'::regclass
          AND conname = 'strategy_state_strategy_instance_id_key'
    ) INTO constraint_exists;
    
    IF NOT constraint_exists THEN
        ALTER TABLE strategy_state ADD CONSTRAINT strategy_state_strategy_instance_id_key 
            UNIQUE (strategy_instance_id);
        RAISE NOTICE 'Added unique constraint on strategy_instance_id';
    END IF;
END $$;

COMMIT;
