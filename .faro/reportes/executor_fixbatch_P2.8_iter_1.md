# Fix Batch Report: P2.8 Fixes

**Date**: 2026-07-02
**Status**: ALL 4 FIXES APPLIED

| Fix | File | Change |
|-----|------|--------|
| F21 | dossier.py | Read existing next_session dossier before writing (preserves comm_style etc.) |
| F22 | test_style.py SA5 | Captures _llm_call args, asserts "architecture"/"relational"/"framing" NOT in extraction prompt |
| F23 | interview_style.py + interviews.py | Removed 'mixed' from VALID_STYLES + regex |
| F24 | interviews.py | start_session loads comm_style from initial dossier JSONB before prepare_dossier |
