# BOT_Cartera_CEDEARS

Sistema autónomo de análisis y gestión de cartera de CEDEARs.

## Research MVP v1.0

El pipeline de Research exige cobertura completa del universo canónico, ranking determinístico y Top-N auditable antes de habilitar valuación profunda y G4.

## Separación análisis / ejecución

El Local Market Layer distingue entre referencia analítica y ejecutabilidad real. Cuando un precio local falta o es claramente inconsistente, G4 puede usar una referencia analítica derivada de subyacente × CCL robusto / ratio validado con `PASS_WITH_WARNING`, pero esto **no** crea bid/ask ni habilita una orden. La ejecución sigue requiriendo datos locales válidos y un libro operable.

Ver `docs/EIGHT_BLOCKER_RECOVERY.md` para el contrato de recuperación de datos aplicado al Top-30.
