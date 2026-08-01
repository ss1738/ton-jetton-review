# Security Review — TON Reference Jetton (TEP-74)

**Target:** `ton-blockchain/token-contract` · `ft/jetton-minter.fc`, `ft/jetton-wallet.fc`, `ft/jetton-utils.fc`, `ft/op-codes.fc`, `ft/params.fc`
**Method:** manual review + **machine-checked invariants (z3)** — see `invariants.py`, runnable in ~1s.
**Reviewer:** Satyawan Singh · formal-verification-backed review
**Date:** 2026-08-01

> Scope note & honesty statement. This is the *reference* Jetton the ecosystem forks; it is hardened and
> widely reviewed. This report does not manufacture criticals in battle-tested code. Its value is (a) the
> **machine-checked invariants** below — a proof artifact, not a claim — and (b) the **fork-time footguns**,
> because that is where the bugs in *deployed* jettons actually live. Severities are calibrated to the
> reference as-deployed (admin trusted). Every ✅/severity that cites z3 is reproducible from `invariants.py`.

## System model

A jetton is a minter + one wallet contract per owner. A wallet's address is a **deterministic** function of
`(owner, master, wallet_code)` via the state-init hash (`jetton-utils.fc`). This derivation is the root of
trust: a wallet credits an incoming `internal_transfer` only if the sender is the master (a mint) or the
wallet address computed for the claimed `from` owner (a genuine sibling wallet). No global registry is needed.

Wallet storage: `balance:Coins, owner, master, wallet_code`. Handlers: `transfer`→`send_tokens`,
`internal_transfer`→`receive_tokens`, `burn`→`burn_tokens`, bounced msg→`on_bounce`.

## Invariants (machine-checked — `invariants.py`)

| # | Invariant | Status |
|---|-----------|--------|
| **I1** | `balance >= 0` is preserved by every handler (send/receive/burn/on_bounce) as written | ✅ **PROVED (z3)** |
| **G** | The guard `throw_unless(706, balance >= 0)` is *necessary* — remove it and a negative balance is reachable | ✅ counterexample `balance=0, amount=1` |
| **A** | Balance can only *decrease* via the owner (705) and only *increase* via master or a derived sibling wallet (707) | ✅ by construction (address-derivation binding) |
| **C** | Global conservation `total_supply == Σ(wallet balances)` | ⚠️ **violated on the mint-bounce path — see F1** |

## Findings

### F1 — `total_supply` desyncs from circulating supply on a bounced mint · **Low** (admin-scoped) · *conservation*
`jetton-minter.fc` `op::mint` increments `total_supply` (`save_data`, line 68) in the same transaction that
*sends* the `internal_transfer` to the target wallet, but `recv_internal` **silently drops bounced messages**
(`if (flags & 1) { return (); }`, lines 49–51). If that mint message bounces — uninitialized/failed wallet
init, a malformed `master_msg`, or under-provisioned forward value — the tokens are never credited yet
`total_supply` is already increased. Result: `total_supply > Σ balances`, permanently, and every consumer of
`get_jetton_data().total_supply` (explorers, DeFi price/oracle logic, other contracts) reads an inflated
supply. **z3 witness:** `mint_amount=1, delivered=0 ⇒ supply_after=1, sum_after=0` (`invariants.py`, block C).
Admin-triggered in the reference ⇒ Low. **Fork escalation:** any fork that exposes mint to a non-admin or
semi-trusted role turns this into an attacker-influenced supply-inflation bug — re-rate to **High** there.
*Remediation:* track supply on confirmed credit (increment on a mint-ack / decrement on the mint bounce in an
`on_bounce` path), or treat `total_supply` as an upper bound and document it as such.

### F2 — Minter does not validate the inner `master_msg` op/shape · **Informational** (admin-scoped)
`op::mint` does `master_msg_cs~skip_bits(32 + 64)` and reads `coins`, but never checks that `master_msg`'s op
is `internal_transfer`. A malformed `master_msg` makes the target wallet `throw(0xffff)` → bounce → F1 desync.
*Remediation:* assert the inner op equals `op::internal_transfer()` before minting.

### F3 — `burn_notification` decrements `total_supply` with no floor check · **Informational** (defense-in-depth) · *conservation*
`jetton-minter.fc` `op::burn_notification` does `total_supply - jetton_amount` (line 78) with no
`throw_unless(total_supply - jetton_amount >= 0)`. In the honest model this cannot underflow (a wallet can
only burn what it holds, and `Σ balances ≤ total_supply`). But the contract **relies on a global invariant it
does not locally enforce** — and F1 already shows that invariant is violable. With 257-bit signed ints, an
underflow yields a garbage/near-max supply. *Remediation:* add the floor check; it costs one gas unit and
makes the local code robust to any upstream conservation drift.

### F4 — Hardcoded fee constants become wrong under fork/config drift · **Informational** (documented in-code)
`min_tons_for_storage` (0.01 TON) and `gas_consumption` (0.015 TON) are literals; the code comments (lines
15–22) already warn they must be revisited on global-fee changes, larger wallet code, or a different
workchain. A fork that adds storage fields (larger code) or deploys cross-workchain without re-tuning risks
under-provisioned messages and failed sends. *Remediation:* re-derive on any fork; prefer
`msg_fwd_fee`-based calculation (noted at line 94) where universality matters.

### F5 — No zero-amount guard on `transfer`/`burn` · **Informational**
A zero-amount `transfer` still derives the destination wallet and emits the inter-wallet message chain,
consuming gas for a no-op; not a safety issue. *Remediation (optional):* early-return on `jetton_amount == 0`.

## What is solid (assurances)

- **Balance safety (I1) is correctly enforced on every decrement path** (705 owner-check, 706 non-negativity),
  and machine-checked here. This is the property that matters most and it holds.
- **Anti-mint binding (707)** via deterministic wallet-address derivation is sound — no wallet can be credited
  by an impostor.
- **Bounce compensation is correct:** `on_bounce` restores `balance` for exactly the two decrementing outbound
  ops (`internal_transfer`, `burn_notification`), so a failed async transfer cannot burn the sender's tokens.
- **Correct message modes:** bounceable `0x18` for inter-wallet/mint (so failures are recoverable), and
  non-bounceable `0x10` for notifications to possibly-uninitialised owners (so they can't strand value).
- **Throws are in the compute phase, not the action phase** — the code reasons about this explicitly
  (lines 108–110, 164–165), which is what makes the bounce-restore in F1/`on_bounce` fire correctly.

## Reproduce

```bash
python3 invariants.py     # needs z3-solver; proves I1, shows guard necessity, exhibits the F1 witness
```

## Summary

No critical or high-severity issue in the reference as-deployed (admin trusted). One real **conservation**
weakness (F1, Low here / High in permissionless forks) plus defense-in-depth hardening (F2, F3). The balance-
safety invariant that protects user funds is **machine-checked and holds**. The recurring theme — and the
thing a forker must carry forward — is that the contracts lean on a *global* invariant (`supply == Σ balances`)
that no single contract locally enforces; F1 and F3 are where that gap shows.
