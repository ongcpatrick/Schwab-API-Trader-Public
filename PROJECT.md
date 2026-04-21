# Project Brief

## One-Line Pitch

`A local-first Schwab trading copilot that helps analyze performance, enforce discipline, and execute only guardrailed trades through the official API.`

## Outcome

- Primary outcome: Improve trading discipline and decision quality by automating journaling, evaluation, and risk enforcement.
- Success metric: The system captures all trades, blocks unsafe orders reliably, and supports a preview-first path to live execution with no unauthorized submissions.

## Audience

- Primary audience: The Schwab account owner operating their own brokerage account(s)
- Secondary audience: Future collaborators helping maintain the system

## Scope

### In Scope

- OAuth and token lifecycle management for Schwab API access
- Read-only sync for accounts, balances, positions, orders, transactions, and market data
- Automated trade journal and post-trade evaluation
- Strategy evaluation and signal-generation modules
- Risk policy engine for sizing, limits, and execution gating
- Order drafting, `previewOrder`, and controlled live order submission

### Out Of Scope

- Selling this as a third-party auto-trading product for other users
- Unsupervised fully autonomous trading without explicit policy controls
- Website automation for workflows already covered by the Schwab API
- High-frequency or latency-sensitive trading infrastructure

## Structure

- Main sections or features:
- authentication and broker connectivity
- read-only portfolio and market data ingestion
- trade journal and analytics
- strategy evaluation and recommendations
- risk-gated execution and audit logging

## Content Or Data

- Source of truth: `external API + local database`
- Needs auth: `yes`
- Needs forms: `minimal`
- Needs search/filtering: `yes`

## Design Direction

- Visual style: `technical`
- References: professional trading workstation, compliance dashboard, research notebook
- Colors to avoid: `hype-driven neon trading UI styling`
- Motion level: `low`

## Technical Constraints

- Hosting target: `local-first`, optional `Docker`
- Browser/device priorities: `desktop-heavy`
- SEO needed: `no`
- Accessibility expectations: `baseline for any UI we expose`

## Risks

- Schwab OAuth and token refresh behavior can be brittle and time-sensitive.
- Some Schwab portal details are client-rendered and may need manual verification.
- Order schemas are complex enough that malformed requests can have financial consequences.
- Sandbox or paper-trading coverage for the API is not yet fully confirmed in this workspace.

## Open Questions

- What instruments should we support first: equities only, or equities plus options?
- What level of autonomy do you want after preview mode: manual approve-each, rules-based auto-execution, or hybrid?
- Do you want a local web dashboard, CLI-first workflow, or both?
