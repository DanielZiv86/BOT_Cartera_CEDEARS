# ROADMAP MVP — Cartera CEDEAR

## Objetivo activo
Finalizar y validar el MVP real end-to-end del sistema autónomo de gestión de cartera CEDEAR para compra de vivienda en USD.

Regla permanente: **ningún cambio puede aumentar la complejidad del sistema si antes no elimina una limitación demostrada del MVP.**

Método obligatorio: **problema observado → evidencia objetiva → causa raíz → corrección mínima → validación → documentación.**

## Alcance MVP
Pipeline objetivo: Universe → Prices → Market Features → Portfolio State → Research → Local Market → Valuation → G4 Cash Hurdle → Risk → Committee.

Los agentes recomiendan y persisten información; nunca ejecutan operaciones.

## Mandato de inversión
- Objetivo: preservar y hacer crecer capital destinado a compra de vivienda en USD.
- Horizonte objetivo: 12 meses; máximo razonable: 24 meses.
- Prioridad: preservación de capital en USD y control de drawdown.
- Universo: CEDEARs vigentes verificados contra fuentes oficiales.
- IWDA permanece incluido como excepción explícita de mandato.
- Costos: 0,60% compra + 0,60% venta (~1,20% ida y vuelta).
- Preferencia: hasta 10 posiciones.
- Performance principal: USD.
- Cash es una posición estratégica válida.

## Research MVP v1.0 — CERTIFICADO 2026-09-07

Research fue reconstruido para que la falta parcial de una feature no elimine silenciosamente instrumentos del ranking. La ausencia de evidencia queda separada de la calidad de inversión mediante Data Quality y Uncertainty Penalty.

### Contrato certificado
- Una decisión de screening por cada CEDEAR del universo canónico de mandato.
- Factores universales: momentum 6m, tendencia vs MA200, volatilidad 63d, max drawdown y momentum 3m.
- Score cross-sectional 0–100.
- Missing data: contribución neutral explícita + penalización por incertidumbre; nunca relleno presentado como dato observado.
- Data Quality Score independiente.
- Scoring Model ID por tipo de instrumento.
- Ranking determinístico completo sin huecos ni duplicados.
- Top-N sujeto a piso de Data Quality.
- Research Integrity Gate fail-closed.
- Artifacts de métricas, integridad y reconciliación.

### Validación real en main
Workflow run: `34113961514`.

Resultado:
- canonical mandate universe: 305
- screening records: 305
- valid scores: 305
- coverage: 100.00%
- ranked: 305
- missing ranks: 0
- duplicate ranks: 0
- mean Data Quality: 100.00
- zero-observation tickers: 0
- Top-N: 30
- PASS: 77
- WATCH: 121
- FAIL: 107
- Research Integrity Gate: PASS
- unit tests: PASS
- workflow: SUCCESS

### Reconciliación 316 vs 305
El source master declara `Eligible_Count=316`, pero ese número es anterior al overlay de mandato. La configuración vigente excluye explícitamente 12 tickers del análisis y agrega IWDA como excepción de mandato. Por lo tanto, el universo canónico correcto consumido por Research es `316 - 12 + 1 = 305`. Research no debe reintroducir instrumentos explícitamente excluidos para forzar una cifra nominal. El workflow obtiene el expected count desde `universe_manifest.json`, evitando hardcodes y detectando cualquier futura divergencia entre Universe y Research.

## Baseline de Valuation previo a esta certificación
- metodología VAL-1.7
- equity 268 / ETF 37
- ready 283 / blocked 22
- coverage 92,79%
- Finnhub 429 = 0
- BLOCKED_BY_DATA legítimo permanece como comportamiento correcto en Valuation/G4.

## Criterio de salida MVP
Objetivo de validación sostenida: 30 corridas diarias consecutivas con workflows estables, datos no inventados, outputs trazables, runtime estable, cobertura aceptable y Committee coherente y auditable.
