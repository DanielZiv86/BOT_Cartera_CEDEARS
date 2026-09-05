# MVP-First Development Policy

## Purpose
This document defines the permanent development policy for this project.

## Core Principle
Validate the Minimum Viable Product (MVP) before investing in platform architecture.

## Freeze Rule
Until the MVP is demonstrated as stable, the following initiatives remain frozen:
- New platform architecture.
- Artifact Registry implementation.
- Python Orchestrator.
- Scheduler redesign.
- System Health dashboard.
- Data Lake redesign.
- Additional optimization not required to stabilize the MVP.

These ideas remain in the long-term roadmap and must not be implemented until the MVP exit criteria are met.

## MVP Goal
Operate the CEDEAR portfolio autonomously with consistent, auditable daily decisions.

## MVP Scope
Only these engines are in scope:
- Universe
- Prices
- Market Features
- Portfolio State
- Valuation
- G4 Cash Hurdle
- Risk
- Committee

## Definition of Done
The MVP is considered validated only after sustained successful operation (target: 30 consecutive daily runs) with:
- No workflow failures.
- No fabricated data.
- Consistent Committee decisions.
- Traceable outputs.
- Stable runtime.
- Acceptable data coverage.

## Development Rule
Every proposed improvement must answer one question:

Does this change directly improve MVP stability or correctness?

If the answer is NO, the work moves to the post-MVP backlog.

## Documentation Rule
Every accepted change must update:
- CHANGELOG
- ROADMAP
- Relevant technical documentation
- This policy if the development strategy changes.
