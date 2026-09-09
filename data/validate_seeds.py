"""Confirm every deliberately-injected ambiguity is present in the seed data.

If a check fails, the corresponding gotcha in semantic/DEFINITIONS.md has no
evidence behind it and should not be claimed.
"""
import os
import pandas as pd

D = os.path.join(os.path.dirname(__file__), "seeds")
r = lambda f: pd.read_csv(os.path.join(D, f))

subs = r("subscribers.csv")
txn = r("transactions.csv")
ref = r("refunds.csv")
per = r("subscription_periods.csv")
evt = r("store_events.csv")
test = r("test_accounts.csv")

for df, col in [(txn, "purchased_at"), (ref, "refunded_at"), (evt, "event_at"),
                (per, "started_at"), (per, "ended_at")]:
    df[col] = pd.to_datetime(df[col], format="ISO8601", utc=True)

checks = []


def check(name, ok, detail):
    checks.append((name, bool(ok), detail))


# 1. sandbox
sb = (txn.environment == "sandbox").mean()
check("sandbox transactions present", 0.01 < sb < 0.06, f"{sb:.2%} of transactions")

# 2. internal test accounts
tst = len(test) / len(subs)
check("internal test accounts present", 0.005 < tst < 0.03,
      f"{len(test)} accounts ({tst:.2%} of subscribers)")

# 3. late-landing refunds
m = ref.merge(txn[["transaction_id", "purchased_at"]], on="transaction_id")
lag = (m.refunded_at - m.purchased_at).dt.days
check("refunds land late", lag.median() > 20,
      f"median lag {lag.median():.0f}d, p90 {lag.quantile(.9):.0f}d, max {lag.max():.0f}d")

# 4. sub-hour trial cancellations
ts = evt[evt.event_type == "trial_start"][["original_transaction_id", "event_at"]]
tc = evt[evt.event_type == "trial_cancel"][["original_transaction_id", "event_at"]]
j = ts.merge(tc, on="original_transaction_id", suffixes=("_start", "_cancel"))
mins = (j.event_at_cancel - j.event_at_start).dt.total_seconds() / 60
insta = (mins < 60).sum()
check("sub-hour trial cancellations", insta > 100,
      f"{insta:,} trials cancelled <60min ({insta/len(ts):.2%} of all trial starts)")

# 5. repeat trialers
per_sub = evt[evt.event_type == "trial_start"].groupby("subscriber_id").size()
repeat = (per_sub > 1).sum()
check("repeat trialers", repeat > 100,
      f"{repeat:,} subscribers started >1 trial")

# 6. billing retry / grace period
statuses = per.status.value_counts().to_dict()
check("billing_retry + grace_period states exist",
      statuses.get("billing_retry", 0) > 0 and statuses.get("grace_period", 0) > 0,
      f"billing_retry={statuses.get('billing_retry',0):,}, grace_period={statuses.get('grace_period',0):,}")

# 7. voluntary vs involuntary churn
ct = per.churn_type.value_counts().to_dict()
check("both churn types present", ct.get("voluntary", 0) > 0 and ct.get("involuntary", 0) > 0,
      f"voluntary={ct.get('voluntary',0):,}, involuntary={ct.get('involuntary',0):,}")

# 8. annual plans (MRR amortization)
ann = txn.product_id.str.contains("annual").mean()
check("annual plans present", ann > 0.10, f"{ann:.1%} of transactions are annual plans")

# 9. cross-platform identity
multi = subs.groupby("app_user_id").subscriber_id.nunique()
check("cross-platform identity collisions", (multi > 1).sum() > 100,
      f"{(multi>1).sum():,} humans hold >1 subscriber_id (max {multi.max()})")

# 10. FX drift
fx = txn[txn.currency == "BR"].groupby(txn.purchased_at.dt.to_period("Q")).fx_rate_at_purchase.mean()
check("FX rates drift over time", fx.nunique() > 1,
      f"BRL rate moved {fx.iloc[0]:.4f} -> {fx.iloc[-1]:.4f} across quarters")

# 11. product changes
pc = (evt.event_type == "product_change").sum()
check("mid-lifecycle product changes", pc > 100, f"{pc:,} product_change events")

# 12. mixed commission rates
cr = txn.store_commission_rate.nunique()
check("mixed store commission rates", cr >= 3,
      f"{cr} distinct rates: {sorted(txn.store_commission_rate.unique())}")

# ---- report
w = max(len(n) for n, _, _ in checks)
print(f"\n{'CHECK':<{w}}  RESULT  DETAIL")
print("-" * (w + 60))
for name, ok, detail in checks:
    print(f"{name:<{w}}  {'PASS' if ok else 'FAIL':<6}  {detail}")

failed = [n for n, ok, _ in checks if not ok]
print()
if failed:
    print(f"{len(failed)} FAILED: {', '.join(failed)}")
    raise SystemExit(1)
print(f"All {len(checks)} injected conditions confirmed present.")

# ---- the headline number: tracked vs realized divergence
print("\n--- tracked vs realized revenue (production, non-test, all time) ---")
clean = txn[(txn.environment == "production") & (~txn.subscriber_id.isin(test.subscriber_id))]
tracked = clean.price_usd.sum()
clean_ref = ref[ref.transaction_id.isin(clean.transaction_id)]
refunded = clean_ref.refund_amount_usd.sum()
commission = (clean.price_usd * clean.store_commission_rate).sum()
print(f"tracked revenue (gross)     ${tracked:>14,.2f}")
print(f"  less refunds              ${-refunded:>14,.2f}  ({refunded/tracked:.2%})")
print(f"  less store commission     ${-commission:>14,.2f}  ({commission/tracked:.2%})")
print(f"realized revenue (net)      ${tracked-refunded-commission:>14,.2f}"
      f"  ({(tracked-refunded-commission)/tracked:.1%} of tracked)")
