
## 1. Limitations

These limitations come from the two-day datathon scope and the trial Snowflake platform. They affect how far the results can be generalised, and each one is addressed in our recommendations.

- **Different city and climate:** The data is from Kitchener, Canada, not Watercare's network. Freezing winters cause many of its breaks, so the patterns may not carry over to Auckland.
- **No inspection or CCTV data:** The score relies on break history and pipe attributes. We did not use CCTV data because we wanted to minimise the number of Snowflake credits used.
- **Built in two days on a trial platform:** We had one XSMALL warehouse, a 40 credit cap, and no review by an actual maintenance planner.
- **Very rare events:** Only about 0.5% of pipes break in a year, so results from the 2022-2025 backtest can swing a lot. We judge the ranking by how many real breaks the top-ranked pipes catch, not by accuracy.
- **A target of 0 does not mean no leak:** It only means no matching, repaired break was recorded. Unreported leaks and unlinked breaks are counted as "no break".
- **The pipe register is a current snapshot:** Fields such as material, condition score and criticality are today's values, not what they were on 1 January of each year, which could let future information leak into the backtest.
- **Patchy and assumed data:** Breaks before 1997 are unreliable, and we assumed pipe IDs match across files, that "Asset Size (cm)" is really millimetres, and that breaks dated before a pipe's install date belong to a replaced pipe.

## 2. Recommendations

These are the next steps we would take to move from a datathon prototype to something a maintenance planner could trust. We will focus on better data and local validation.

- **Add condition data:** Bring in real inspection records, CCTV defect grades and maintenance logs, which is the original problem the use case describes.
- **Test on Watercare's data:** Retrain and backtest on local pipes before anyone acts on the ranking.
- **Add weather and environment data:** Temperature, freeze days, soil and water pressure would help explain the winter spike in breaks.
- **Rebuild a historical snapshot of the register:** Features should reflect what was known on each 1 January, which removes the risk of future data leaking in.
- **Involve planners:** Show the ranking to real maintenance planners, record what they inspect and find, and feed that back into the model.

## Learnings

