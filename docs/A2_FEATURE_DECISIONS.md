# A2: feature engineering decisions

A plain log of what we decided while building the ML training table, and why.
If something looks wrong further down the pipeline, start here.

Code: `delay_features/main.py` (`make features`). Settings: `shared/config.py`, under "A2 delay features".

## Background: how an arrival is measured (A1)

- A1 reads every bus's GPS position every 15 s. Each reading is a **ping**.
- It keeps only pings of the chosen routes within 500 m of a chosen stop.
- The **arrival time** is the time of the ping closest to the stop (`gtfs_position_collection/arrivals.py`).
- There is no real "bus arrived" signal, so this is an estimate. The closer that ping was, the better the estimate.

## One row = one bus arriving at one stop on one day

Key: trip + stop + date. All later steps work on these rows.

## What the model predicts (target)

| Class | Delay (observed − scheduled) |
|---|---|
| early | more than 1 min early |
| on time | 1 min early to 5 min late |
| late | more than 5 min late |

- **Why classes, not minutes:** the arrival time is only accurate to roughly a minute, so exact minutes would be false precision.
- Bands live in config: `EARLY_MINUTES`, `LATE_MINUTES`.

## What the model gets (inputs)

| Input | Where it comes from | Why |
|---|---|---|
| route | arrivals | routes differ in how late they run |
| stop | arrivals | stops differ (traffic lights, busy corners) |
| quadrant (N/E/S/W) | stops table | side of the city |
| window (am / midday / pm) | the collection window the scheduled time falls in | peaks behave differently |
| day type (weekday / weekend) | service date | weekend traffic differs; the weekday itself was dropped because with about 2 weeks each weekday occurs only twice, so it would mostly identify the date |
| headway | timetable: minutes to the previous bus of the same route at that stop | frequent routes bunch and pick up delay differently |
| previous-stop delay | the same bus's delay at its previous chosen stop (worked out before any rows are dropped, so a dropped stop still counts as the previous stop) | delays carry forward; usually the strongest input |
| has previous stop | 1 or 0 | at the first stop there is no previous delay; this tells "unknown" apart from "exactly on time" |
| precipitation | weather for the scheduled hour | rain slows traffic and boarding |

Rule: every input must be available for a live query too. So window and weather use the **scheduled** time, never the observed time.

## Things we left out on purpose

| Left out | Why |
|---|---|
| Ping distance as an input | It describes how good our measurement is, not the bus. It is also unknown before the bus arrives. We use it as a filter instead. |
| Temperature, wind, weather code | Little real effect on buses. With about 12 days, extra weather columns mostly just identify the day, so the model would memorise days. |
| Operator's ETA (Adelaide Metro `trip_updates`) | Not collected, and too late to start. It is used live only, in the reasoning step, not in training. |
| Category encoding (one-hot etc.) | Done in the training step, so it is fitted on training data only. |

## Rows we drop, and why

Rows are dropped in this order. Each dropped row is counted once, under the first reason that applies, so the counts add up. Each run prints them.

Before any of this, the previous-stop delay and headway are worked out on all rows, so dropping a row doesn't change them for the others.

| # | Reason | Why |
|---|---|---|
| 1 | No scheduled time | Some timetable stops have no time. With nothing to compare against, the row can't be labelled. |
| 2 | Closest ping too far (over `MAX_ARRIVAL_PING_M`, 250 m) | The arrival time could be off by about a minute, enough to land in the wrong class. **250 m is a placeholder:** pick the final value from the distance spread printed on real data. |
| 3 | Scheduled near a window edge (within `EDGE_MARGIN_MINUTES`, 10 min, of a window's start or end) | A bus due at 17:55 that runs late arrives after 18:00, when collection has stopped, so it is never seen. The same happens with early buses at a window's start. Keeping these rows would leave fewer late and early buses in the data than really happened. So only 07:10–08:50, 12:10–13:50 and 16:10–17:50 are used. A bus more than 10 min late can still be missed, but that is rare. |
| 4 | Window not fully collected (no stored ping within `WINDOW_COVERAGE_MINUTES`, 5 min, of the window's start and of its end) | The same bias as rule 3, for a whole window: if collection started late or stopped early, only buses late or early enough to fall in the collected part were seen. Added 4 Nov for the final database, whose last day stops at 12:35; it also drops 1 Nov's morning, which started at 07:43. |
| 5 | No headway | The route has only one bus at that stop that day. |
| 6 | No quadrant | The stop wasn't chosen for this route (it was chosen for another route that shares it). |
| 7 | No weather | That hour's weather is missing. Should be close to 0, since rule 3 keeps every row inside a window hour. |

## How headway is worked out

- Old timetable versions aren't kept, so we can't look up which services ran on a past date.
- Instead, a service counts as running on a date if at least one of its trips was seen that day.
- Each date uses one timetable version: the one holding the most of that day's seen trips (the newest on a tie). Service ids are reused across versions while trip ids are renumbered, so mixing versions puts an old trip next to its replacement.
- Risk: a service that ran but had none of its trips seen is missing, so the headway looks bigger than it really was.

## Training the models (`delay_model`, `make train`)

| Decision | Why |
|---|---|
| Test on the **last 3 days**, cross-validate on the rest in folds of **whole days** | Buses on the same day share weather and incidents. Splitting inside a day lets the model see that day's conditions in training, so scores look better than they are. |
| 5 folds, or 3 if a fold would have fewer than 5 late buses | Too few late buses in a fold makes its late-recall meaningless. The run prints the late count per fold. |
| Baseline: **"same class as the previous stop"**, as a rule and as a small logistic regression on that delay alone | Delays carry forward, so this simple rule is hard to beat. Every model is reported as its gain over it. The regression version gives probabilities, so it can be compared on log-loss too. |
| Models: logistic regression, random forest, gradient boosting | Readable and close to linear; interactions on small data; the most accurate end. The spec asks for at least 3. |
| **Small fixed grids**, all combinations tried | With about 13 independent days, a big or random search finds settings that fit noise. |
| **No class weights** | They push "p(late)" up on purpose, so the number Prolog reads would stop being a real probability. Caution about late buses is handled in Prolog's rules. |
| Winner = **lowest CV log-loss** | Prolog uses the probability, so probability quality decides. Macro-F1 and late recall are still reported. |
| Calibration only if it helps | Sigmoid calibration is tried on the winner and kept only if CV log-loss drops. Isotonic was left out: too few late buses. |
| Gradient boosting's early stopping is off | It holds out random rows, which mixes days and repeats the leak above. |
| Test results come with **95% intervals** (whole trips resampled 1,000 times) | The test days may hold only 10–20 late buses, so one bus moves late recall by 5–10%. |
| Results split by **first stop vs later stops** | At the first stop there is no previous delay; that is where the models really differ. |

Left out on purpose: random search, isotonic calibration, nested CV, a "no previous stop" ablation, cost-weighted thresholds, and predicting minutes then converting to classes (worth one line as future work).

## Hybrid vs ML alone (`make hybrid_vs_ml`)

From the council review on 1 Nov. Code: `reasoner/`, `hybrid_engine/`, `hybrid_vs_ml/`.

| Decision | Why |
|---|---|
| No offline "operator vs ML vs hybrid" score | Operator estimates and alerts were never stored. Offline, every answer takes the "no operator estimate" branch. The report says this up front instead of hiding it. |
| Operator and alert rules: plunit tests + constructed cases + one live recording | The only honest evidence without stored data. Constructed cases are labelled as such. |
| Hybrid compared with **ML at the same threshold**, not only with ML argmax | "Warn if p(late) ≥ 1/3" is one line of Python. Comparing at the same threshold shows what the rules add on their own. If nothing, the report says so. |
| Early warnings scored too, not just late | An early bus leaves before the passenger arrives. That is the worse miss. |
| Thresholds fixed in config before the test days are seen (`P_WARN` 1/3, `CONF_MEDIUM` 0.5, bunching 25% / long gap 150% of headway) | Tuning them on the test days would make the test scores meaningless. |
| Bunching uses classes only, no class-to-minutes mapping | The model predicts classes. Turning them into minutes would be an invented stand-in. |
| Only bus pairs whose warning existed before the leader arrived | A warning that comes after the bus has gone is no use. |
| No precision/recall below 10 real events | On a handful of events, a rate is noise. Counts and cases are reported instead. |
| Replays (`--at`) only use what was known then | A previous-stop delay counts only if that stop was passed. The arrival itself never reaches the rules. A test checks this. |
| Test cases are picked by code from the test days and replayed through `ask --at` | Reproducible, and the cases are not cherry-picked. One case is chosen where the rules make it worse. |

Left out on purpose: storing answers in a `hybrid_answers` table (files instead), cost-weighted totals, stacked rain/OR triggers, collecting live snapshots.

Not built yet: live mode (`ask` without `--at`, reading Adelaide Metro feeds) and the `alerts` and `bunching` queries.

## Fixed issues

Found by the council review on 1 Nov and fixed the same day. Each has a test in `tests/test_delay_features.py`.

1. **Window-edge bias.** Late buses near a window's end and early buses near its start were never seen, so the data had too few late and early buses.
   *Fixed:* drop rule 3 above.
2. **"Previous stop" could skip a stop.** The previous-stop delay was worked out after the far-ping filter, so if stop B was dropped, stop C used A as its "previous stop".
   *Fixed:* it is now worked out before any filter.
3. **Drop counts overlapped.** A row missing both headway and weather was counted twice.
   *Fixed:* rows are dropped one reason at a time.
4. **`make features` didn't refresh arrivals first,** so it could run on stale arrivals.
   *Fixed:* `features` now depends on `arrivals` in the Makefile.
5. **Fake headways from old timetable versions** (found 2–3 Nov on the first real data). The database holds 4 GTFS versions (1705–1714). Service "1" is in all of them, but trip ids were renumbered, so a superseded trip (1133958, 13:27) sat next to its replacement (1176415, 13:28): a 1 min headway. 827 of 2,554 rows had a headway under 3 min, and 1,151 rows had a wrong headway in all. That broke a model input, the bunching/long-gap ground truth and bus pairing.
   *Fixed:* one timetable version per date (see "How headway is worked out"). Afterwards headways run 5–48 min (median 15), and bus pairs went from 212 to 293.

## Known issues (open)

None right now. Add new ones here with the date and a one-line fix idea.

## Check when the real database arrives

The collection data lives on a teammate's machine, so none of this has run on real data yet.

- The drop counts. Any reason with a surprisingly large number needs a look.
- The distance spread, to set the final ping cutoff.
- The smallest and largest `delay_min`. Delays of ±30 min or more probably mean a bus was matched to the wrong trip.
- How many timetable versions there are. If more than one, check that no headway is 0.
- Class balance and rows per day.
- Run `make train QUICK=1` first (about a minute). Check the late count per fold it prints. If it falls back to 3 folds or warns, there are too few late buses, so read the late scores with care.
- If "early" has almost no rows, decide before 4 Nov whether to merge it into "on time".

## Say these in the report

- First paragraph of the evaluation: operator estimates and alerts were not stored, so those rules are tested by unit tests, constructed cases and one live run only.
- If the hybrid's warnings equal the plain threshold's (`hybrid_equals_threshold` in `reports/hybrid_vs_ml/metrics.json`), the rules' value is the trace, the guards and the bus pairs, not accuracy.
- The timing-point veto assumes buses wait at timing points. Check `safety.csv`: if early recall drops, that assumption does not hold in the data. Report it as brittleness.
- Replays use the observed rain for the hour; live would use a forecast.

- The gaps between the tuned models are probably within CV noise; check the ± spreads and test intervals before calling one "better".
- With about 13 days, every result rests on few independent days.

- The model predicts **one stop ahead**: it needs the delay at the previous stop.
- Precipitation is the rain in the **hour before** (that is how Open-Meteo reports it), from a weather model. A live query would use a forecast.
- Headway comes from observed trips in training and from the timetable calendar in live use.
- The arrival time is the closest 15 s ping, so labels near the class edges carry some noise.
- The 10 min edge margin and why it is there (rule 3).
- Compare the model to a simple rule, "predict the same class as the previous stop". Delays carry forward, so beating that rule is the real test.
