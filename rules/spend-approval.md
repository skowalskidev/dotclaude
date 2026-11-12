# Spend approval: paid calls always, free allowances past a cap

**DO get an explicit per-call "yes" before ANY billable operation** (paid render, credit-consuming
API call, metered request; a subscription run is none). Name it and its rough cost, then WAIT. One
yes is ONE call, never a batch, sweep or retry loop.
**DO treat Simon's direct ask to run billable work with a bound** ("a bit", "a few", "under $5")
as the yes for the smallest set meeting it: name the calls and rough cost, then run them with no
second confirmation. Never exceed the bound or retry past it.
**DON'T treat a diagnose / fix / test task as license to spend.** It covers reading logs, code and
data and free calls under the cap below (a rejected invalid request bills nothing); never a paid
call to test a guess, or a bisection that fires paid calls until one works.
WHY: paid render credits burned bisecting a bug after being told not to spend.

**DO treat a free or trial allowance as scarce** (one-time credits, monthly free tier, trial
searches): at most 5 calls or 10% of it, whichever is smaller, without a yes. Keep the rest for
verification and debugging. Make each call answer a distinct question (cost per call, per-person
pricing, a coverage edge case). (the fix for a 94-of-100 free-trial bake-off)

TEST: every billable call traces to a per-call yes, and no run spends over 5 calls or 10% of a free
allowance without one; a fix task is never that yes. Simon's bounded ask is never re-asked or
exceeded (the fix for re-asking after "run the billable tests, just a bit").
