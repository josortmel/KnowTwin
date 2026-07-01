# ADR-003: Migración de Oracle a PostgreSQL

**Estado**: Aprobada
**Fecha**: 2024-11-20
**Decisor**: Comité de Arquitectura

## Contexto

El sistema de reconciliación actual usa Oracle 19c. Los costes de licencia y la falta de extensiones vectoriales motivan la migración.

## Decisión

Migrar a PostgreSQL 16 con pgvector para capacidades de búsqueda semántica.

## Responsable de ejecución

Maria Lopez lidera la migración como arquitecta principal. Timeline: Q3 2025.

## Consecuencias

- Reducción de costes de licencia ~60%
- Acceso a pgvector para futuras funcionalidades de IA
- Riesgo de regresión en procedimientos almacenados legacy
- Necesidad de reentrenamiento del equipo DBA
