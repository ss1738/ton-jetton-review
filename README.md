# TON Jetton — formal-verification-backed security review

A security review of the **TON reference Jetton (TEP-74)** — the fungible-token
contracts (`ton-blockchain/token-contract`) that most TON jettons fork — with the
core safety invariants **machine-checked by z3**, not just asserted.

- **[AUDIT.md](AUDIT.md)** — the report: system model, invariants, findings (severity-calibrated), assurances.
- **[invariants.py](invariants.py)** — the proof artifact: run it, and z3 proves the balance-safety
  invariant, shows the guard that enforces it is necessary, and exhibits a concrete counterexample for the
  conservation finding (F1).
- **[src/](src/)** — the exact contracts reviewed (upstream reference, unmodified).

```bash
python3 invariants.py     # needs z3-solver
```

## Why this is different from a manual review

Most jetton reviews are best-effort manual reads. This one states the invariants formally and **machine-checks
them**: `balance >= 0` is *proved* preserved by every message handler, and the global conservation invariant
`total_supply == Σ balances` is *shown* to break on the mint-bounce path with an SMT witness. On TON's async
actor model — where the real bugs are message-ordering and bounce handling — that rigor catches what a manual
pass misses.

No critical/high in the reference as-deployed. The value is the machine-checked assurance on the property that
guards user funds, plus the fork-time footguns (F1–F4) that bite deployed jettons.

*Reviewer: Satyawan Singh.*
