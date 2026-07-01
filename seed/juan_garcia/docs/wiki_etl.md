# ETL Pipeline — Documentación Técnica

**Última actualización**: 2024-08-15
**Propietario**: Maria Lopez

## Arquitectura

El pipeline ETL procesa transacciones bancarias desde los sistemas core de Banco Norte hacia el data warehouse de reporting.

## Capacidad

El ETL está diseñado para manejar hasta **100.000 transacciones por día**. El procesamiento se ejecuta en ventanas nocturnas de 4 horas (02:00-06:00).

## Componentes

1. **Extractor**: lectura desde Oracle (será PostgreSQL post-migración)
2. **Transformador**: reglas de negocio en Python
3. **Loader**: inserción en el data warehouse

## Monitorización

- Grafana dashboard: grafana.internal/d/etl-pipeline
- Alertas: PagerDuty canal #etl-alerts
- Logs: ELK stack, retención 30 días

## Incidencias conocidas

- El proceso se ralentiza significativamente por encima de 80K transacciones
- Los reintentos automáticos no funcionan para errores de conexión Oracle
