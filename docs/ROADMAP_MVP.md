# ROADMAP MVP — Cartera CEDEAR

## Objetivo activo
Finalizar y validar el MVP real end-to-end del sistema autónomo de gestión de cartera CEDEAR para compra de vivienda en USD.

Regla permanente: **ningún cambio puede aumentar la complejidad del sistema si antes no elimina una limitación demostrada del MVP.**

Método obligatorio: **problema observado → evidencia objetiva → causa raíz → corrección mínima → validación → documentación.**

No crear nueva arquitectura, engines, dashboards, registries, orchestrators ni refactors que no sean necesarios para cerrar una limitación reproducida del MVP.

## Alcance MVP
Pipeline objetivo:
1. Universe
2. Prices
3. Market Features
4. Portfolio State
5. Research / Screening MVP
6. Local Market
7. Valuation VAL-1.7
8. G4 Cash Hurdle
9. Risk
10. Committee

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

## Estado validado

### Research MVP — CERRADO
- Screening determinístico sobre universo canónico completo.
- Componentes: momentum 6m, tendencia vs MA200 y volatilidad 63d (menor es mejor).
- Ranking determinístico, Top-N default 30.
- Inputs materiales faltantes => BLOCKED_BY_DATA.
- Validación real: 305/305 scoreable, 0 bloqueados, tests PASS.
- Merge a main completado.

### BRKB / Finnhub — CERRADO
- Causa raíz: símbolo canónico BRK/B incompatible con convención Finnhub BRK.B.
- Normalización implementada y aplicada a endpoints Finnhub.
- Corrida real posterior: BRKB pasó a VALUATION_READY.
- Sin regresión agregada.

### VAL-1.7 — BASELINE
Corrida real de 305 CEDEARs:
- metodología VAL-1.7
- equity 268 / ETF 37
- baseline posterior a BRKB: ready 283 / blocked 22
- coverage 92,79%
- Finnhub requests 387
- Finnhub 429 = 0
- No se deben modificar thresholds, freshness ni budgets para forzar 305/305.
- BLOCKED_BY_DATA legítimo es comportamiento correcto.

## PROBLEMA ACTIVO AL CIERRE — VEA / VIG Vanguard
Este es el único frente que se estaba resolviendo al cerrar la sesión del 2026-09-06.

### Evidencia oficial
Vanguard publica holdings de VIG y VEA. VIG mostraba 333 holdings con fecha 2026-07-31 en la página oficial, por lo que la información existe y la fecha sería compatible con el freshness permitido para VIG.

### Historial de causa raíz ya descartado
1. Parser HTML genérico no reconocía correctamente la columna HOLDINGS → corregido, pero no resolvió adquisición.
2. GitHub runner carecía de html5lib → agregado.
3. Luego faltaba BeautifulSoup/html parser → agregado.
4. Con dependencias presentes, Vanguard respondió HTTP 200 pero pandas encontró `No tables found` → se confirmó que la página es client-rendered y el scraping HTML no es una solución correcta.
5. Se migró a endpoint JSON oficial/público de Vanguard:
   `https://investor.vanguard.com/investment-products/etfs/profile/api/<TICKER>/portfolio-holding/stock?start=1&count=50000`
6. Corrida real 34068837187 terminó SUCCESS pero mostró para VEA y VIG:
   `VANGUARD_JSON_INVALID: Expecting value: line 1 column 1 (char 0)`
   Esto probó que el endpoint estaba devolviendo una respuesta no JSON al cliente del runner.

### Última corrección implementada — PENDIENTE DE VALIDACIÓN REAL
Se verificó contra una implementación pública reciente del cliente Vanguard que los endpoints son keyless pero requieren un User-Agent de navegador completo; de lo contrario Vanguard puede devolver HTML/interstitial en vez de JSON.

Se corrigió directamente sobre `main`, sin crear nueva rama:
- User-Agent completo de Chrome para requests Vanguard.
- Header `Accept: application/json`.
- Se mantiene el endpoint JSON de holdings.
- Diagnóstico enriquecido para registrar Content-Type y muestra de body si vuelve una respuesta no JSON.
- No se modificaron budgets, freshness, thresholds ni metodología VAL-1.7.

**Último commit al cierre:** `75477f199b870d9d57e2ff09a8c43c3f45c2ba69`

## PRIMERA ACCIÓN DE LA PRÓXIMA SESIÓN
No diseñar nada nuevo. No crear ramas. No tocar política de valuación.

1. Buscar la corrida `Build Canonical Valuation Scenarios` correspondiente al commit `75477f199b870d9d57e2ff09a8c43c3f45c2ba69` en `main`.
2. Revisar logs exactos de VEA y VIG.
3. Éxito esperado:
   - `VANGUARD_JSON_DIAGNOSTIC ticker=VEA status=200 holdings=<nonzero> as_of=<valid date>`
   - `VANGUARD_JSON_DIAGNOSTIC ticker=VIG status=200 holdings=<nonzero> as_of=<valid date>`
   - sin `VANGUARD_PRIMARY_DIAGNOSTIC` para VEA/VIG.
4. Confirmar en artifacts:
   - provider Vanguard
   - source_tier ISSUER_OFFICIAL
   - source_ref endpoint JSON
   - fecha real de holdings
   - VIG sin ETF_HOLDINGS_STALE si la fecha entra en freshness.
5. Comparar métricas agregadas contra baseline ready283 / blocked22 / coverage92,79% y verificar 429=0 o controlado.
6. Si falla, usar exclusivamente el nuevo diagnóstico de Content-Type/body para identificar la causa exacta y aplicar la corrección mínima directamente en `main`.
7. Si funciona, declarar Vanguard CERRADO y pasar al siguiente blocker real del MVP.

## Blockers conocidos para revisar DESPUÉS de cerrar Vanguard
No corregirlos preventivamente.
- VEA puede seguir bloqueado por lookthrough/mapeo de tickers internacionales incluso con holdings oficiales correctos. Evaluar sólo con evidencia de la nueva corrida.
- SMH: holdings previamente stale; inspeccionar fuente primaria VanEck sólo cuando Vanguard esté cerrado.
- IWDA: parser iShares UCITS falla y fallback StockAnalysis 404; tratar como causa separada.
- G4: existe antecedente de posible versión top-level G4-1.0 sobrescribiendo G4-1.1; corregir sólo si sigue reproducible después de cerrar Valuation.

## Política de ramas durante el cierre del MVP
El usuario pidió explícitamente dejar de crear ramas para estas correcciones y trabajar directamente sobre `main`.
Las ramas históricas mergeadas pueden eliminarse como housekeeping, pero esto no debe distraer del cierre del MVP.

## Criterio de salida MVP
Objetivo de validación sostenida: 30 corridas diarias consecutivas con:
- workflows estables
- datos no inventados
- outputs trazables
- runtime estable
- cobertura aceptable
- Committee coherente y auditable

Hasta cumplirlo, todo desarrollo post-MVP permanece congelado.
