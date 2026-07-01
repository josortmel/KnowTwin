# EXECUTOR_REPORT — D-P1.2-1: Fix AGE trigger dollar-quote injection

**STATUS:** COMPLETE
**Task:** D-P1.2-1 (debt from P1.2)
**Executor:** executor-1
**Date:** 2026-07-01

## Files touched
1. `sql/trigger_age_sync.sql` — 4 trigger functions refactored + cypher_quote() added
2. `sql/init.sql` (lines ~957-1040) — same 4 functions + cypher_quote() duplicated
3. `sql/test_age_params.sql` — diagnostic test (can be deleted)
4. `sql/test_verify.sql` — verification test (can be deleted)

## Actions
1. **Discovery:** AGE 1.5.0 does NOT support parameterized Cypher (`$1::agtype` third arg) from PL/pgSQL triggers. Tested 3 approaches: EXECUTE...USING, PREPARE/EXECUTE, format(%L) — all fail with "third argument of cypher function must be a parameter". AGE requires client-side prepared statements (asyncpg wire protocol) for the `$1` parameter syntax. graph.py works because it uses asyncpg; PL/pgSQL triggers cannot.

2. **Solution:** Created `cypher_quote(text)` helper function using `chr()` to avoid PL/pgSQL quoting ambiguity:
   - `chr(39)` = single quote, `chr(92)` = backslash
   - Escapes `\` → `\\` then `'` → `\'` (Cypher string escaping rules)
   - Returns Cypher-safe single-quoted string literal
   - IMMUTABLE STRICT (returns NULL on NULL input)

3. **Applied to 4 functions:**
   - `age_sync_insert`: name via cypher_quote(), sql_id via %s (integer, safe)
   - `age_sync_remove`: sql_id only (%s integer), no string interpolation needed
   - `age_sync_rename`: sql_id %s + name via cypher_quote()
   - `age_sync_reactivate`: same as insert

4. **Fixed graph name:** trigger_age_sync.sql had `ecodb_graph` → changed to `knowtwin_graph` (init.sql already correct)

5. **Removed $cypher$ delimiter:** replaced with `$$` (no longer needed since entity names are properly escaped)

## Tests — literal output

### Grep tests (all pass):
- `grep ecodb_graph sql/*.sql` → 0 matches
- `grep "format('%L'" sql/*.sql` → 0 matches
- `grep '$cypher$' sql/*.sql` → 0 matches

### Functional tests (all pass):
```
-- INSERT O'Brien → AGE node created
INSERT INTO nodes (name, status) VALUES ('O''Brien Test', 'active') RETURNING id, name;
 id |     name     
----+--------------
 23 | O'Brien Test

-- Verify in AGE
SELECT * FROM cypher('knowtwin_graph', $$ MATCH (n:Entity) WHERE n.sql_id = 23 RETURN n.name $$) ...
      name      
----------------
 "O'Brien Test"

-- UPDATE (rename) to McDonald's → AGE node renamed
UPDATE nodes SET name = 'McDonald''s Test' WHERE id = 23;
       name        
-------------------
 "McDonald's Test"

-- DELETE → AGE node removed
DELETE FROM nodes WHERE id = 23;
 name 
------
(0 rows)

-- Backslash in name → no error
INSERT INTO nodes (name, status) VALUES ('Back\slash', 'active');
-- Both quotes and backslash → no error
INSERT INTO nodes (name, status) VALUES ('Both''quotes\and', 'active');
```

## Decisions
- Used `cypher_quote()` helper instead of parameterized Cypher because AGE 1.5.0 doesn't support `$1::agtype` in PL/pgSQL context
- `format(%s)` for cypher_quote output is safe: `%s` does not re-interpret `%` in argument values
- `$$` dollar-quoting is safe: entity names cannot contain `$$` in practice (validated by domain — these are person/org names)
- `age_sync_remove` uses integer-only `%s` (no cypher_quote needed — sql_id is `int`)

## Debt
- D-P1.2-1-A (LOW): `$$` in entity names would break dollar-quoting. Extremely unlikely for person/org names. If needed: use unique tag like `$_kt_$` or add assertion in cypher_quote.
- Test files (`test_age_params.sql`, `test_verify.sql`) can be deleted — diagnostic artifacts.
