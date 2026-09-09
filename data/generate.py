"""
Generate a synthetic, RevenueCat-shaped subscription dataset.

The point of this generator is NOT to produce clean data. It deliberately
injects the conditions that make subscription metrics ambiguous, because the
semantic layer in ../semantic/ exists to resolve exactly those ambiguities.

Injected messiness (each maps to a documented gotcha in DEFINITIONS.md):
  1.  Sandbox transactions          -> must be always-filtered
  2.  Internal test accounts        -> must be always-filtered
  3.  Refunds landing 5-70 days late-> tracked vs realized revenue divergence
  4.  Sub-hour trial cancellations  -> "what counts as a trial start?"
  5.  Repeat trialers               -> trial starts != unique users trialing
  6.  Billing retry / grace period  -> "is this subscriber active?"
  7.  Voluntary vs involuntary churn-> two different business problems
  8.  Annual plans                  -> MRR amortization question
  9.  Cross-platform identity       -> one human, several subscriber rows
  10. Local currency + FX drift     -> which FX rate, on which date?
  11. Mid-period product changes    -> upgrade/downgrade revenue attribution
  12. Store commission 30% vs 15%   -> gross vs net realized revenue

Usage:  python3 data/generate.py [--subscribers N] [--seed S]
Writes CSV seeds to data/seeds/.
"""

import argparse
import csv
import os
import random
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- config

START = datetime(2025, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 6, 30, tzinfo=timezone.utc)
SEEDS_DIR = os.path.join(os.path.dirname(__file__), "seeds")

STORES = [("app_store", 0.52), ("play_store", 0.36), ("stripe", 0.12)]

PRODUCTS = [
    # product_id, store-agnostic name, period, usd list price, trial days
    ("premium_monthly", "Premium Monthly", "P1M", 9.99, 7),
    ("premium_annual", "Premium Annual", "P1Y", 79.99, 14),
    ("pro_monthly", "Pro Monthly", "P1M", 19.99, 7),
    ("pro_annual", "Pro Annual", "P1Y", 159.99, 14),
    ("premium_weekly", "Premium Weekly", "P1W", 3.99, 0),
]

COUNTRIES = [
    # code, fx rate to USD at START, annual drift, share
    ("US", 1.00, 0.00, 0.34),
    ("GB", 1.27, -0.04, 0.09),
    ("DE", 1.09, -0.03, 0.11),
    ("BR", 0.20, -0.12, 0.10),
    ("IN", 0.012, -0.05, 0.13),
    ("JP", 0.0067, -0.09, 0.07),
    ("CA", 0.74, -0.02, 0.06),
    ("AU", 0.66, -0.03, 0.05),
    ("MX", 0.058, -0.06, 0.05),
]

CHANNELS = [
    ("organic", 0.38),
    ("apple_search_ads", 0.16),
    ("meta_ads", 0.19),
    ("google_ads", 0.13),
    ("tiktok_ads", 0.08),
    ("referral", 0.06),
]

# App Store / Play Store take 30%, or 15% under small-business programs.
# Stripe is ~2.9% + 30c; modelled as a flat effective rate here.
COMMISSION = {"app_store": (0.30, 0.15), "play_store": (0.30, 0.15), "stripe": (0.029, 0.029)}


def weighted(pairs):
    vals, ws = zip(*pairs)
    return random.choices(vals, weights=ws, k=1)[0]


def rand_dt(start, end):
    delta = (end - start).total_seconds()
    return start + timedelta(seconds=random.uniform(0, delta))


def fx_rate(country_code, at):
    """FX drifts over time. Converting at transaction date != converting today."""
    for code, base, drift, _ in COUNTRIES:
        if code == country_code:
            years = (at - START).days / 365.25
            return round(base * (1 + drift * years), 6)
    return 1.0


def period_delta(period):
    return {"P1W": timedelta(days=7), "P1M": timedelta(days=30), "P1Y": timedelta(days=365)}[period]


# ---------------------------------------------------------------- generate

def generate(n_subscribers, seed):
    random.seed(seed)

    subscribers, transactions, refunds, periods, events, test_accounts = [], [], [], [], [], []

    txn_seq = 0
    period_seq = 0
    event_seq = 0
    refund_seq = 0

    # ---- cross-platform identity: some humans get 2-3 subscriber rows
    n_humans = int(n_subscribers * 0.94)
    human_ids = [f"user_{i:06d}" for i in range(n_humans)]

    subscriber_rows = []
    for i in range(n_subscribers):
        # ~6% of subscriber rows are a second/third device-or-store identity
        # belonging to a human who already appears above.
        if i >= n_humans:
            app_user_id = random.choice(human_ids)
        else:
            app_user_id = human_ids[i]
        subscriber_rows.append(app_user_id)

    for idx, app_user_id in enumerate(subscriber_rows):
        sub_id = f"sub_{idx:06d}"
        country = weighted([(c, s) for c, _, _, s in COUNTRIES])
        store = weighted(STORES)
        channel = weighted(CHANNELS)
        first_seen = rand_dt(START, END - timedelta(days=3))

        # 1.5% of accounts are internal QA / employee accounts
        is_internal = random.random() < 0.015
        if is_internal:
            test_accounts.append({"subscriber_id": sub_id, "reason": random.choice(
                ["qa_automation", "employee_account", "demo_account", "load_test"])})

        subscribers.append({
            "subscriber_id": sub_id,
            "app_user_id": app_user_id,
            "first_seen_at": first_seen.isoformat(),
            "country": country,
            "store": store,
            "attribution_channel": channel,
        })

        # ---- how many separate subscription lifecycles this subscriber has
        # Most have one. Some churn and come back months later (repeat trialers).
        n_lifecycles = random.choices([1, 2, 3], weights=[0.86, 0.12, 0.02])[0]
        cursor = first_seen

        for life in range(n_lifecycles):
            if cursor > END:
                break
            # gap before a returning subscriber starts again
            if life > 0:
                cursor += timedelta(days=random.randint(150, 420))
                if cursor > END:
                    break

            product_id, _, period, usd_price, trial_days = random.choice(PRODUCTS)
            # 3% of ALL traffic is sandbox / StoreKit test environment
            environment = "sandbox" if random.random() < 0.03 else "production"
            # small-business commission rate applies to ~55% of accounts
            comm_full, comm_small = COMMISSION[store]
            commission_rate = comm_small if (store != "stripe" and random.random() < 0.55) else comm_full

            original_txn_id = f"otxn_{idx:06d}_{life}"
            purchased_at = cursor
            rate = fx_rate(country, purchased_at)
            local_price = round(usd_price / rate, 2) if rate else usd_price

            has_trial = trial_days > 0
            converted = False
            trial_end = None

            # ------------------------------------------------ trial phase
            if has_trial:
                trial_end = purchased_at + timedelta(days=trial_days)
                txn_seq += 1
                transactions.append({
                    "transaction_id": f"txn_{txn_seq:08d}",
                    "original_transaction_id": original_txn_id,
                    "subscriber_id": sub_id,
                    "product_id": product_id,
                    "store": store,
                    "environment": environment,
                    "period_type": "trial",
                    "is_renewal": 0,
                    "purchased_at": purchased_at.isoformat(),
                    "expires_at": trial_end.isoformat(),
                    "price_usd": 0.0,
                    "price_local": 0.0,
                    "currency": country,
                    "fx_rate_at_purchase": rate,
                    "store_commission_rate": commission_rate,
                })
                event_seq += 1
                events.append({
                    "event_id": f"evt_{event_seq:08d}", "subscriber_id": sub_id,
                    "original_transaction_id": original_txn_id, "event_type": "trial_start",
                    "event_at": purchased_at.isoformat(), "product_id": product_id,
                    "store": store, "environment": environment,
                })

                # ~8% of trials are cancelled within the first hour.
                # Do these count as trial starts? DEFINITIONS.md answers this.
                insta_cancel = random.random() < 0.08
                if insta_cancel:
                    cancel_at = purchased_at + timedelta(minutes=random.randint(2, 59))
                    event_seq += 1
                    events.append({
                        "event_id": f"evt_{event_seq:08d}", "subscriber_id": sub_id,
                        "original_transaction_id": original_txn_id, "event_type": "trial_cancel",
                        "event_at": cancel_at.isoformat(), "product_id": product_id,
                        "store": store, "environment": environment,
                    })
                    period_seq += 1
                    periods.append({
                        "period_id": f"per_{period_seq:08d}", "subscriber_id": sub_id,
                        "original_transaction_id": original_txn_id, "product_id": product_id,
                        "store": store, "environment": environment,
                        "started_at": purchased_at.isoformat(), "ended_at": trial_end.isoformat(),
                        "status": "expired", "auto_renew_status": 0, "is_trial": 1,
                        "churn_type": "voluntary",
                    })
                    cursor = trial_end
                    continue

                # trial converts?
                conv_rate = 0.42 if period == "P1M" else 0.51
                converted = random.random() < conv_rate

                period_seq += 1
                periods.append({
                    "period_id": f"per_{period_seq:08d}", "subscriber_id": sub_id,
                    "original_transaction_id": original_txn_id, "product_id": product_id,
                    "store": store, "environment": environment,
                    "started_at": purchased_at.isoformat(), "ended_at": trial_end.isoformat(),
                    "status": "expired", "auto_renew_status": 1 if converted else 0,
                    "is_trial": 1, "churn_type": None if converted else "voluntary",
                })

                if not converted:
                    event_seq += 1
                    events.append({
                        "event_id": f"evt_{event_seq:08d}", "subscriber_id": sub_id,
                        "original_transaction_id": original_txn_id, "event_type": "trial_cancel",
                        "event_at": (trial_end - timedelta(hours=random.randint(1, 48))).isoformat(),
                        "product_id": product_id, "store": store, "environment": environment,
                    })
                    cursor = trial_end
                    continue

                paid_start = trial_end
                event_seq += 1
                events.append({
                    "event_id": f"evt_{event_seq:08d}", "subscriber_id": sub_id,
                    "original_transaction_id": original_txn_id, "event_type": "trial_conversion",
                    "event_at": paid_start.isoformat(), "product_id": product_id,
                    "store": store, "environment": environment,
                })
            else:
                paid_start = purchased_at
                event_seq += 1
                events.append({
                    "event_id": f"evt_{event_seq:08d}", "subscriber_id": sub_id,
                    "original_transaction_id": original_txn_id, "event_type": "initial_purchase",
                    "event_at": paid_start.isoformat(), "product_id": product_id,
                    "store": store, "environment": environment,
                })

            # ------------------------------------------------ paid renewals
            renewal_n = 0
            current_product, current_usd = product_id, usd_price
            pd = period_delta(period)
            active_from = paid_start

            while active_from < END:
                rate = fx_rate(country, active_from)
                local = round(current_usd / rate, 2) if rate else current_usd
                txn_seq += 1
                txn_id = f"txn_{txn_seq:08d}"
                expires = active_from + pd
                transactions.append({
                    "transaction_id": txn_id,
                    "original_transaction_id": original_txn_id,
                    "subscriber_id": sub_id,
                    "product_id": current_product,
                    "store": store,
                    "environment": environment,
                    "period_type": "normal",
                    "is_renewal": 1 if renewal_n > 0 else 0,
                    "purchased_at": active_from.isoformat(),
                    "expires_at": expires.isoformat(),
                    "price_usd": round(current_usd, 2),
                    "price_local": local,
                    "currency": country,
                    "fx_rate_at_purchase": rate,
                    "store_commission_rate": commission_rate,
                })
                event_seq += 1
                events.append({
                    "event_id": f"evt_{event_seq:08d}", "subscriber_id": sub_id,
                    "original_transaction_id": original_txn_id,
                    "event_type": "renewal" if renewal_n > 0 else "initial_purchase",
                    "event_at": active_from.isoformat(), "product_id": current_product,
                    "store": store, "environment": environment,
                })

                # ---- refunds land LATE. This is the tracked/realized wedge.
                if random.random() < 0.035:
                    lag = random.randint(5, 70)
                    refunded_at = active_from + timedelta(days=lag)
                    refund_seq += 1
                    refunds.append({
                        "refund_id": f"ref_{refund_seq:07d}",
                        "transaction_id": txn_id,
                        "subscriber_id": sub_id,
                        "original_transaction_id": original_txn_id,
                        "refunded_at": refunded_at.isoformat(),
                        "refund_amount_usd": round(current_usd, 2),
                        "reason": weighted([("customer_request", 0.55), ("accidental_purchase", 0.2),
                                            ("fraud", 0.1), ("store_initiated", 0.15)]),
                        "is_partial": 0,
                    })
                    event_seq += 1
                    events.append({
                        "event_id": f"evt_{event_seq:08d}", "subscriber_id": sub_id,
                        "original_transaction_id": original_txn_id, "event_type": "refund",
                        "event_at": refunded_at.isoformat(), "product_id": current_product,
                        "store": store, "environment": environment,
                    })

                # ---- mid-lifecycle product change (upgrade/downgrade)
                if random.random() < 0.04 and renewal_n > 0:
                    candidates = [p for p in PRODUCTS if p[0] != current_product and p[2] == period]
                    new = random.choice(candidates) if candidates else None
                    if new:
                        event_seq += 1
                        events.append({
                            "event_id": f"evt_{event_seq:08d}", "subscriber_id": sub_id,
                            "original_transaction_id": original_txn_id, "event_type": "product_change",
                            "event_at": (active_from + pd / 2).isoformat(), "product_id": new[0],
                            "store": store, "environment": environment,
                        })
                        current_product, current_usd = new[0], new[3]

                # ---- does it renew again?
                monthly_churn = 0.085 if period == "P1M" else (0.13 if period == "P1W" else 0.028)
                churns = random.random() < monthly_churn

                if churns:
                    # involuntary = payment failure. Goes through billing retry,
                    # then grace period, then dies. Very different from a cancel.
                    involuntary = random.random() < 0.34
                    if involuntary:
                        event_seq += 1
                        events.append({
                            "event_id": f"evt_{event_seq:08d}", "subscriber_id": sub_id,
                            "original_transaction_id": original_txn_id, "event_type": "billing_issue",
                            "event_at": expires.isoformat(), "product_id": current_product,
                            "store": store, "environment": environment,
                        })
                        # ~40% of billing retries recover
                        recovered = random.random() < 0.40
                        retry_end = expires + timedelta(days=random.randint(3, 16))
                        period_seq += 1
                        periods.append({
                            "period_id": f"per_{period_seq:08d}", "subscriber_id": sub_id,
                            "original_transaction_id": original_txn_id, "product_id": current_product,
                            "store": store, "environment": environment,
                            "started_at": active_from.isoformat(),
                            "ended_at": retry_end.isoformat(),
                            "status": "billing_retry" if retry_end > END else "expired",
                            "auto_renew_status": 1, "is_trial": 0,
                            "churn_type": None if recovered else "involuntary",
                        })
                        if recovered:
                            active_from = retry_end
                            renewal_n += 1
                            continue
                        cursor = retry_end
                        break
                    else:
                        event_seq += 1
                        events.append({
                            "event_id": f"evt_{event_seq:08d}", "subscriber_id": sub_id,
                            "original_transaction_id": original_txn_id, "event_type": "cancellation",
                            "event_at": (active_from + pd * random.uniform(0.1, 0.9)).isoformat(),
                            "product_id": current_product, "store": store, "environment": environment,
                        })
                        period_seq += 1
                        periods.append({
                            "period_id": f"per_{period_seq:08d}", "subscriber_id": sub_id,
                            "original_transaction_id": original_txn_id, "product_id": current_product,
                            "store": store, "environment": environment,
                            "started_at": active_from.isoformat(), "ended_at": expires.isoformat(),
                            "status": "expired", "auto_renew_status": 0, "is_trial": 0,
                            "churn_type": "voluntary",
                        })
                        cursor = expires
                        break

                # still alive
                status = "active" if expires > END else "expired"
                # a slice of live subscribers are sitting in grace period right now
                if expires > END and random.random() < 0.02:
                    status = "grace_period"
                period_seq += 1
                periods.append({
                    "period_id": f"per_{period_seq:08d}", "subscriber_id": sub_id,
                    "original_transaction_id": original_txn_id, "product_id": current_product,
                    "store": store, "environment": environment,
                    "started_at": active_from.isoformat(), "ended_at": expires.isoformat(),
                    "status": status, "auto_renew_status": 1, "is_trial": 0, "churn_type": None,
                })
                active_from = expires
                renewal_n += 1
                cursor = expires

    return subscribers, transactions, refunds, periods, events, test_accounts


def write_csv(path, rows):
    if not rows:
        return 0
    keys = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subscribers", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    os.makedirs(SEEDS_DIR, exist_ok=True)
    subs, txns, refs, pers, evts, tests = generate(args.subscribers, args.seed)

    out = {
        "subscribers.csv": subs,
        "transactions.csv": txns,
        "refunds.csv": refs,
        "subscription_periods.csv": pers,
        "store_events.csv": evts,
        "test_accounts.csv": tests,
    }
    for name, rows in out.items():
        n = write_csv(os.path.join(SEEDS_DIR, name), rows)
        print(f"{name:28s} {n:>8,} rows")


if __name__ == "__main__":
    main()
