# BOT_Cartera_CEDEARS

Motor de datos y soporte de decisión para una cartera personal de CEDEARs con horizonte principal de 12 meses y objetivo final de preservación y crecimiento de capital en USD.

## Principio de arquitectura

El sistema se divide en dos capas:

1. **Python Data Engine** — adquisición, normalización, persistencia, calidad y cálculo determinista.
2. **Decision & Governance Agents** — Research, Surveillance, Risk, Investment Committee y CIO.

Los agentes no deben reconstruir masivamente datos de mercado que puedan ser producidos de forma reproducible por Python.

## Flujo objetivo

```text
External Sources
  -> Universe Manager
  -> Symbol Mapping
  -> Market Data
  -> Historical Data
  -> Data Quality
  -> Feature / Screening Engine
  -> Research Handoff
  -> Research -> Surveillance -> Risk -> Committee -> CIO
```

## MVP técnico — Fase 1

El primer objetivo del repositorio es construir únicamente:

- Universe Master de CEDEARs.
- Symbol Map CEDEAR -> subyacente/proveedor.
- Underlying Price Layer.
- Historical Price Layer.
- Data Quality Report.
- Handoff estructurado para Research.

Quedan fuera del MVP inicial: fundamentals, ETF analytics, valuation scoring, technical scoring, ranking, G4 y decisiones de cartera.

## Estructura

```text
src/
  connectors/       Adaptadores de fuentes externas
  universe/         Universe Master y symbol mapping
  market_data/      Precios e históricos
  quality/          Validaciones y controles
  persistence/      Lectura/escritura de datasets canónicos
  orchestration/    Pipelines y entrypoints

config/             Configuración no sensible
data/
  canonical/        Estado canónico vigente
  snapshots/        Snapshots históricos inmutables
  handoffs/         Contratos de salida para agentes
logs/                Logs de ejecución
tests/               Tests automatizados
.github/workflows/   GitHub Actions
```

## Reglas de persistencia

- No sobrescribir historia sin trazabilidad.
- Todo dataset debe exponer `run_id`, `data_as_of`, `created_at`, `source` y `version` cuando corresponda.
- Los datos sensibles y credenciales nunca se guardan en el repositorio.
- Los secretos se inyectarán mediante GitHub Actions Secrets.
- Parquet/JSON serán los formatos internos principales; Excel será sólo una capa de reporting posterior.

## Jerarquía de fuentes

La arquitectura admite fallback por ticker:

1. PRIMARY_OFFICIAL
2. SECONDARY_INSTITUTIONAL
3. APPROVED_MARKET_DATA_FALLBACK
4. BLOCKED_BY_DATA

La homogeneidad se obtiene por schema, calidad, fechas, moneda, provenance y reglas comunes; no se exige que todos los tickers provengan del mismo proveedor.

## Convenciones de estado

### Precio
- `PRICE_READY_FRESH`
- `PRICE_READY_STALE`
- `PRICE_BLOCKED`

### Historia
- `HISTORY_READY`
- `SHORT_HISTORY_BY_AGE`
- `HISTORY_BLOCKED`

### Calidad
- `PASS`
- `WARNING`
- `BLOCKED`

## GitHub Actions

Los workflows iniciales son placeholders y no ejecutan todavía lógica financiera pesada. La implementación se habilitará por fases.

Previstos:

- `bootstrap.yml` — validación manual del entorno.
- `daily_market_data.yml` — actualización diaria de mercado.
- `weekly_screening.yml` — futuro refresh semanal de features/screening.

## Mandato y gobernanza

Este repositorio no ejecuta órdenes de compra o venta. Su función es producir información auditable para el sistema de decisión de cartera.
