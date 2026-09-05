# BOT_Cartera_CEDEARS — Roadmap RC1

## Objetivo
Transformar el proyecto desde un conjunto de workflows hacia una plataforma profesional de Investment Research & Portfolio Management.

## Principios
- Data-first architecture.
- Artefactos canónicos y versionados.
- Data contracts entre etapas.
- Un único Run ID end-to-end.
- Trazabilidad y auditoría completas.
- GitHub Actions como ejecutor; la lógica vive en un Orchestrator Python.

## Dominios
1. Data Platform
2. Research
3. Portfolio
4. Decision
5. Operations

## Prioridades RC1
### P0
- Artifact Registry canónico.
- Dependency Graph + Data Contracts.
- Run Manifest único.
- Orchestrator Python.

### P1
- System Health Dashboard.
- Scheduler único.
- QA: Golden Runs, Contract Tests, Regression Tests y Performance Tests.

### P2
- VAL-1.7: Budget Optimizer, IWDA robusto, VEA freshness, G4-1.2, auditoría de blockers.
- Research desacoplado en Screening / Research / Deep Research.

### P3
- Event-driven research.
- Portfolio Optimizer.
- Watchlist Engine.

## Definition of Done RC1
- Runtime <= 9 min.
- Finnhub requests <= 450.
- 0 errores 429.
- Cobertura Valuation >= 93%.
- ETFs READY >= 30.
- IWDA resuelto o bloqueado por causa justificable.
- VEA corregido.
- G4 methodology consistente.
- Auditoría completa.
- Committee ejecutable sobre pipeline completo.

## Próxima meta
Ejecutar una única corrida end-to-end (Research -> Valuation -> G4 -> Risk -> Committee) con un único Run ID y validar RC1 antes de incorporar nuevas funcionalidades.