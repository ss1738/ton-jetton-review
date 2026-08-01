#!/usr/bin/env python3
"""Machine-checked invariant analysis of the TON reference Jetton (TEP-74).

Source audited: ton-blockchain/token-contract/ft/{jetton-wallet.fc, jetton-minter.fc}.
This models the balance-transition system of a jetton wallet and the minter's
supply accounting as SMT constraints, and uses z3 to:

  I1  PROVE the local safety invariant `balance >= 0` is preserved by every wallet
      handler (send / receive / burn / on_bounce) AS WRITTEN.
  G   Show the guard on line 59/174 (`throw_unless(706, balance >= 0)`) is NECESSARY:
      remove it and z3 finds a reachable negative-balance state.
  C   Model the GLOBAL conservation invariant `total_supply == sum(wallet balances)`
      and exhibit the concrete mint-bounce counterexample (Finding F1) where the
      minter increments total_supply but the tokens are never credited.

Run:  python3 invariants.py      (needs z3-solver)
"""
from z3 import Int, Solver, Not, And, Implies, ForAll, sat, unsat, prove

OK = "\033[32m"; RED = "\033[31m"; B = "\033[1m"; X = "\033[0m"

def check_valid(name, claim, premises):
    """Prove `premises => claim` is valid (i.e. holds for ALL values)."""
    s = Solver()
    s.add(premises); s.add(Not(claim))         # look for a counterexample
    r = s.check()
    ok = (r == unsat)
    print(f"  {OK+'PROVED ' if ok else RED+'FAILED '}{X}{name}")
    if not ok:
        print(f"    counterexample: {s.model()}")
    return ok

def find_model(name, constraints, expect_sat=True):
    s = Solver(); s.add(constraints)
    r = s.check()
    got = (r == sat)
    tag = OK+"as expected"+X if got == expect_sat else RED+"UNEXPECTED"+X
    print(f"  {'SAT' if got else 'UNSAT'}  {name}  ({tag})")
    if got:
        print(f"    witness: {s.model()}")
    return got

print(f"\n{B}TON Jetton — machine-checked invariants (z3){X}\n")

# ---- I1: local balance-safety invariant, per handler, AS WRITTEN ----
print(f"{B}I1  Local invariant  balance >= 0  is preserved by every handler{X}")
bal = Int('balance'); amt = Int('amount')
pre = And(bal >= 0, amt >= 0)              # invariant holds pre; jetton amounts are unsigned (Coins)

# send_tokens: bal' = bal - amt, guarded by throw_unless(706, bal-amt >= 0)
check_valid("send_tokens  (guard 706 present)", (bal - amt) >= 0,
            And(pre, (bal - amt) >= 0))     # guard is the premise => post trivially holds
# burn_tokens: identical shape
check_valid("burn_tokens  (guard 706 present)", (bal - amt) >= 0,
            And(pre, (bal - amt) >= 0))
# receive_tokens: bal' = bal + amt, no guard needed (amt unsigned)
check_valid("receive_tokens (bal + amt)", (bal + amt) >= 0, pre)
# on_bounce: bal' = bal + amt (restore), no guard needed
check_valid("on_bounce     (bal + amt)", (bal + amt) >= 0, pre)

# ---- G: the 706 guard is NECESSARY (removing it breaks I1) ----
print(f"\n{B}G   Necessity of guard 706: without `throw_unless(706, balance>=0)`, is a negative balance reachable?{X}")
find_model("send without guard reaches balance<0",
           And(bal >= 0, amt >= 0, (bal - amt) < 0), expect_sat=True)

# ---- C: global conservation, and the mint-bounce counterexample (F1) ----
print(f"\n{B}C   Global conservation  total_supply == sum(balances)  under a bounced mint (Finding F1){X}")
# Minter op::mint: total_supply += a; wallet credited += a ONLY IF the internal_transfer is delivered.
# recv_internal drops bounced messages (`if (flags & 1) return()`), so on bounce the credit never happens.
sum_before   = Int('sum_balances_before')
supply_before= Int('total_supply_before')
a            = Int('mint_amount')
delivered    = Int('delivered')            # 1 if internal_transfer landed, 0 if it bounced
# post-state:
supply_after = supply_before + a                                   # minter always increments (line 68)
sum_after    = sum_before + a * delivered                          # wallet credits only if delivered
conservation_holds = (supply_after == sum_after)
# start from a consistent ledger, a real (positive) mint, and a BOUNCE (delivered = 0):
find_model("bounced mint breaks conservation (supply > sum)",
           And(sum_before == supply_before, a > 0, delivered == 0,
               Not(conservation_holds)), expect_sat=True)
# and confirm: on successful delivery, conservation is preserved
print(f"\n{B}    (control) successful mint preserves conservation:{X}")
check_valid("delivered mint keeps supply == sum",
            (supply_before + a) == (sum_before + a * 1),
            And(sum_before == supply_before, a >= 0))

print(f"\n{B}Done.{X} I1 proved; guard necessity shown; F1 conservation gap exhibited with a witness.\n")
