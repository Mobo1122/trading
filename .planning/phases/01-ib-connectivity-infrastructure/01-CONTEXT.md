# Phase 1: IB Connectivity & Infrastructure - Context

**Gathered:** 2026-03-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Establish reliable IB Gateway connection, project scaffolding, database, cache, configuration system, and paper/live toggle. This is the foundational infrastructure that all subsequent phases (market data, risk engine, agents, dashboard) build on. No trading logic, no market data streaming, no risk rules — just the plumbing.

</domain>

<decisions>
## Implementation Decisions

### IB Gateway Setup
- Run IB Gateway in Docker (community-maintained image)
- System will be deployed on a cloud VPS (AWS/GCP/etc), so containerization aligns with deployment target
- Must handle IB's daily restart window (automatic reconnection required per success criteria)

### Paper/Live Toggle
- Both paper and live modes ready from day one
- Single configuration value switches between paper and live (per success criteria — no code changes required)
- Safety: default to paper if configuration is ambiguous or missing

### Deployment Target
- Cloud VPS (AWS/GCP/etc) — always-on, but adds network hop to IB Gateway
- Docker-based deployment aligns with this target

### Claude's Discretion
- **Configuration format**: Research should determine best approach (env vars, YAML, TOML, or hybrid) for a multi-agent trading system with many configurable parameters (risk limits, connection settings, API keys)
- **Project structure**: Research should determine optimal Python package layout (monolith vs multi-package monorepo) for a system with distinct domains (IB connectivity, risk engine, agents, dashboard)
- **Database & persistence**: Research should determine Docker Compose strategy (all-in-Docker vs hybrid), TimescaleDB hypertable design, Redis usage patterns, schema migration approach, and data retention policy
- **Connection behavior**: Research should determine reconnection strategy, health monitoring thresholds, and failure mode handling based on IB Gateway best practices
- **Secrets management**: Research should determine how to handle API keys and sensitive config for both local dev and cloud deployment

</decisions>

<specifics>
## Specific Ideas

- User is not an IB infrastructure expert — wants research to determine best practices across all areas
- Heavy reliance on research phase to establish patterns that will carry through all 8 phases
- Cloud VPS deployment means Docker Compose is the natural fit for service orchestration

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-ib-connectivity-infrastructure*
*Context gathered: 2026-03-25*
