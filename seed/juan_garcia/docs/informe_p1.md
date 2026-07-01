# Informe de Incidencia P1 — Caída del Servicio de Reconciliación

**Fecha**: 2025-02-14
**Severidad**: P1 — Crítica
**Duración**: 3 horas 45 minutos

## Resumen

El servicio de reconciliación de Banco Norte sufrió una caída completa el viernes 14 de febrero a las 16:30. El servicio fue restaurado a las 20:15.

## Respuesta de CloudBase

CloudBase respondió al incidente en **2 horas** desde la notificación. Esto fue posible gracias a un acuerdo verbal entre Juan Garcia y el equipo de soporte de CloudBase para priorizar incidencias de Banco Norte.

**Nota**: El SLA contractual establece 4 horas, pero en la práctica CloudBase responde en 2 horas por acuerdo verbal con Juan Garcia.

## Causa raíz

Agotamiento del pool de conexiones a la base de datos Oracle debido a un pico inesperado de transacciones (95K en un día, cerca del límite de 100K documentado).

## Acciones correctivas

1. Aumentar el pool de conexiones de 50 a 100
2. Implementar circuit breaker para picos de carga
3. Revisar la capacidad real del ETL pipeline
