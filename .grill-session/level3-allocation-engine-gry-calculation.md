---
section: allocation-engine
subsection: gry-calculation
phase: level3
status: complete
date: 2026-05-17
---

## Implementation Detail

### Price source and units

**Candidate universe (~104 gilts):** `midPrice` from the LSE price-explorer API, using the same `POST api.londonstockexchange.com/api/v1/components/refresh` family already used for the TIDM bridge. Price is per GBP100 nominal and is treated as the market clean price.

**Held gilts in analytics:** use the same LSE daily snapshot whenever the held ISIN appears there, so held-versus-candidate comparisons share one market timestamp. The ii CSV `clean_price_gbp` remains the imported portfolio price and is fallback-only if a held gilt is temporarily missing from the LSE snapshot.

Both paths feed into the same `compute_gry(clean_price_per_100, coupon_pct, maturity_date, settlement_date)` function.

### Settlement date

```python
from govuk_bank_holidays.bank_holidays import BankHolidays
import pandas as pd

_holidays = [h["date"] for h in BankHolidays(division="england-and-wales").get_holidays()]
UK_BUS_DAY = pd.offsets.CustomBusinessDay(holidays=_holidays)

settlement_date = (pd.Timestamp.today() + UK_BUS_DAY).date()  # T+1
```

`UK_BUS_DAY` is a module-level singleton constructed once at import, not re-fetched on every call. The holiday list is refreshed on the same monthly cadence as the gilt reference refresh.

### Coupon schedule generation

Given `dividend_day` (for example `29`) and `dividend_months` (for example `"Jan/Jul"`) from `gilt_reference`:

```python
from dateutil.relativedelta import relativedelta

def coupon_dates(maturity_date, settlement_date):
    """Return [prev_coupon_date, next_coupon_date, ...all remaining...] in order."""
    dates = [maturity_date]
    while dates[-1] > settlement_date - relativedelta(months=6):
        dates.append(dates[-1] - relativedelta(months=6))
    dates.reverse()
    prev = max(d for d in dates if d <= settlement_date)
    future = [d for d in dates if d > settlement_date]
    return prev, future
```

`relativedelta` clamps month-end naturally. DMO coupon dates are not business-day adjusted, so raw calendar dates remain authoritative throughout.

STANDARD coupon periods only in v1. The implementation depends only on the coupon calendar fields already stored in `gilt_reference`; it does not require an `issue_date` column. If a gilt cannot be represented cleanly from the available DMO-derived fields, exclude it from that day's derived analytics with a named warning rather than extending the persisted reference contract.

### Ex-dividend date

```python
from datetime import timedelta

def ex_dividend_date(next_coupon_date):
    try:
        return (pd.Timestamp(next_coupon_date) - 7 * UK_BUS_DAY).date()
    except Exception:
        # Beyond the holiday horizon: approximate as 10 calendar days before.
        return next_coupon_date - timedelta(days=10)
```

Settlement is in ex-dividend period when `settlement_date > xd_date`.

### Accrued interest (ICMA actual/actual)

```python
def accrued_interest(coupon_pct, prev_coupon_date, next_coupon_date,
                     settlement_date, xd_date):
    dividend = coupon_pct / 2.0  # per GBP100 nominal, half-coupon
    s = (next_coupon_date - prev_coupon_date).days
    r_days = (settlement_date - prev_coupon_date).days
    accrued_fraction = r_days / s
    if settlement_date > xd_date:
        accrued_fraction -= 1.0
    return accrued_fraction * dividend
```

### GRY plus modified-duration solver

```python
from scipy import optimize
import numpy as np

def compute_gry(clean_price_per_100, coupon_pct, maturity_date, settlement_date):
    """
    Returns (gry_annual, modified_duration_years) or (None, None) on failure.
    Implements DMO-equivalent formulae for STANDARD coupon periods.
    """
    prev_coupon, future_coupons = coupon_dates(maturity_date, settlement_date)
    next_coupon = future_coupons[0]
    xd = ex_dividend_date(next_coupon)

    accrued = accrued_interest(coupon_pct, prev_coupon, next_coupon, settlement_date, xd)
    dirty_price = clean_price_per_100 + accrued

    c = coupon_pct
    f = 2.0
    d1 = c / f
    d2 = c / f
    n = len(future_coupons) - 1

    r = (next_coupon - settlement_date).days
    s = (next_coupon - prev_coupon).days

    if settlement_date > xd:
        d1 = 0.0

    if n == 0:
        y = f * (((d1 + 100.0) / dirty_price) ** (s / r) - 1.0)
        t = r / s
        mod_dur = (t / f) / (1 + y / f)
        return y, mod_dur

    def fn(v):
        return (v ** (r / s) * (
            d1 + d2 * v
            + c * v**2 / (f * (1 - v)) * (1 - v ** (n - 1))
            + 100.0 * v**n
        ) - dirty_price)

    v0 = 1.0 / (1.0 + 0.05 / f)

    try:
        v = optimize.newton(fn, v0)
    except RuntimeError:
        try:
            v = optimize.brentq(fn, 0.01, 0.9999)
        except (RuntimeError, ValueError):
            return None, None

    y = (1.0 / v - 1.0) * f

    times = np.arange(r / s, r / s + n + 1)
    cash_flows = np.full(n + 1, d2)
    cash_flows[0] = d1
    cash_flows[-1] += 100.0
    discount = v ** times
    pv_weighted = np.sum(times * cash_flows * discount)
    macaulay_semi = pv_weighted / dirty_price
    mod_dur = (macaulay_semi / f) / (1.0 + y / f)

    return y, mod_dur
```

### Failure handling

- `RuntimeError` from Newton falls back to `brentq` with bracket `[0.01, 0.9999]` in `v` space.
- If both solvers fail, return `(None, None)`, omit that instrument from the day's `gilt_price_cache` write set, and surface the degraded instrument list through application warnings or source-level refresh detail rather than standalone `refresh_log` warning rows.
- `gilt_price_cache` keeps only successful solves, so persisted `gry_pct` and `modified_duration_years` remain non-null and failed instruments are excluded from optimizer candidate lists and GRY ranking for that run.
- Valid LSE-priced gilts should converge under Newton in the normal case; the fallback path is defensive.

### Storage

`gilt_price_cache(cache_date, isin, clean_price_gbp, gry_pct, modified_duration_years, coupon_pct, maturity_date, fetched_at)` is populated at daily refresh for every gilt whose price and solver output are valid for that run.

- `clean_price_gbp` stores the LSE `midPrice` per GBP100 nominal
- `gry_pct` stores annual GRY as a percentage
- `modified_duration_years` stores modified duration in years
- `fetched_at` captures the refresh timestamp for the persisted snapshot

The source-level refresh row for `lse_gilt_prices` remains terminal-only (`completed` or `failed`) and is not used as a per-instrument warning ledger.

## Decisions Made

- LSE price-explorer API is the live market source for gilt analytics
- One LSE daily market snapshot is authoritative for both held and candidate gilt comparisons; ii CSV prices remain import and fallback data only
- All prices are normalised to per GBP100 nominal before entering the solver
- STANDARD coupon periods only in v1; the implementation does not widen the reference-data contract with `issue_date`
- Coupon schedule generation works backwards from maturity using the DMO coupon calendar with no business-day adjustment
- Ex-dividend handling uses England and Wales business days with a calendar fallback beyond the holiday horizon
- Newton is the first solve path and `brentq` is the fallback
- Failed solves are omitted from the daily cache and surfaced as warnings rather than being stored as null-valued cache rows
- Modified duration is computed analytically from the same cash-flow array; no extra pricing library is required

## Remaining Open Questions

None
