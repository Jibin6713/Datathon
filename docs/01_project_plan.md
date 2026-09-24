# Data Nerds (Team 9) - Project Plan

Use case 1: Infrastructure leak forecasting
UoA Datathon, 23-25 September 2026. Submission due Friday 25 September before 11:30am.

## 1. Problem definition

Water utilities like Watercare have thousands of pipes but only a limited number of crews and a limited budget. Information that could show which pipes are about to fail (inspection records, CCTV, maintenance history, past breaks) is spread across different systems, so it is hard to know which pipes to look at first.

Our user is a maintenance planner. We want to give them a ranked list of water mains, ordered by how likely each one is to break in the next 12 months, with the top 3 reasons for each pipe, shown on a dashboard.

We are using open data from the City of Kitchener (Canada) because it is real and public, and it has both a pipe register and a break history:

- Water Mains: 16,213 active pipes (material, size, install date, criticality)
- Water Main Breaks: 3,020 break records from 1985 to September 2026

We don't have inspection or CCTV data, so we use break history and pipe details instead. Inspection and CCTV data would be added later.

What we found when exploring the data:
- Pipes that break once tend to break again (635 pipes have broken 2 or more times)
- About 30% of cast iron pipes have broken, compared with about 2% of PVC pipes
- Most breaks happen in winter (January has about 6 times more than April)
- Only around 0.5% of pipes break in a year, so we measure how many real breaks our top-ranked pipes catch, not overall accuracy

## 2. Scope

Must have:
- Data loaded into Snowflake (RAW, STAGING, CURATED)
- Data quality checks
- Asset data model and a yearly feature table
- A simple rule-based risk score with the top 3 drivers per pipe
- Streamlit dashboard
- Roles, cost limits and CI/CD

Should have:
- A machine learning model compared against the rule-based score
- Criticality (how bad a failure would be) added to the ranking
- Testing the ranking on 2022-2025 breaks

Could have:
- Short AI-written summaries for the top-risk pipes (using Cortex)
- Map view
- Weather data

Won't have:
- CCTV video analysis
- Real-time data
- Anything outside AWS or Snowflake

## 3. Approach

Kitchener CSV files are loaded into Snowflake. RAW keeps the files as they came in, STAGING cleans them up and flags bad rows, and CURATED holds the data model, features and risk scores. A Streamlit app in Snowflake shows the results to the planner.

A few rules we are sticking to:
- Start with a simple score we can explain. Only use ML if it does better.
- Only use data from before each point in time when building features, so the model isn't "seeing the future".
- Don't delete bad data, flag it, so we can explain what was left out and why.

## 4. Team

| Role | Who | Responsible for |
|---|---|---|
| Project coordinator | Karlo, Khalid | Board, stand-ups, timekeeping, decision log, presentation |
| Cloud engineer | Jibin, Khalid | Snowflake setup, roles, Terraform, CI/CD, cost monitoring |
| Data engineer | Wayne | Loading data, staging, data quality checks, data model |
| Data scientist / analyst | Aritha, Sun | Target, risk score, model, drivers, evaluation, dashboard |
| Solution designer | Everyone | Architecture diagram, dashboard design, technical design |

Everyone commits to GitHub and should be able to explain their own code.

## 5. Tasks

Estimates are in hours.

Day 1 - Wednesday 23 September (done)

| # | Task | Owner | Hours | Status |
|---|---|---|---|---|
| 1 | Pick use case, define problem, assign roles | Everyone | 1 | Done |
| 2 | Find and compare datasets | Khalid | 1.5 | Done |
| 3 | Explore the data and check the two files join | Khalid | 1 | Done |
| 4 | Set up Snowflake (database, warehouse, roles, credit limit) | Jibin | 1.5 | Done |
| 5 | GitHub repo and first architecture draft | Everyone | 0.5 | Done |

Day 2 - Thursday 24 September

| # | Task | Owner | Hours | Needs |
|---|---|---|---|---|
| 6 | Check permissions work | Khalid | 0.25 | 4 |
| 7 | Set up the task board | Karlo | 1 | - |
| 8 | Load raw data | Wayne | 1 | 4 |
| 9 | Staging tables and data quality checks | Wayne | 1.5 | 8 |
| 10 | Asset and break tables | Wayne | 1.5 | 9 |
| 11 | Yearly feature table and target | Wayne, Sun | 2 | 10 |
| 12 | Rule-based risk score and drivers | Sun | 2 | 11 |
| 13 | Test the ranking on 2022-2025 | Sun | 1.5 | 12 |
| 14 | Streamlit app skeleton (with dummy data first) | Aritha | 2 | - |
| 15 | Terraform for the Snowflake setup | Jibin | 2 | 4 |
| 16 | CI/CD | Jibin | 2 | 9 |
| 17 | Cost monitoring | Khalid | 1 | 4 |
| 18 | Decision log and data quality summary | Karlo | 1 | 9 |
| 19 | Full dashboard (ranking, pipe details, filters) | Aritha | 2 | 12, 14 |
| 20 | ML model vs rule-based score (if time) | Aritha, Sun | 2 | 13 |
| 21 | Architecture diagram and technical design | Everyone | 1.5 | 12 |
| 22 | AI summaries for top pipes (if time) | Khalid | 1.5 | 19 |

Day 3 - Friday 25 September

| # | Task | Owner | Hours | Needs |
|---|---|---|---|---|
| 23 | Fix bugs, no new features | Everyone | 1 | - |
| 24 | Testing results, limitations, learnings, future plans | Karlo | 1 | 13 |
| 25 | Presentation slides | Karlo, Khalid | 1 | 19, 21 |
| 26 | Practise the presentation (5 min + 2 min questions) | Everyone | 0.5 | 25 |
| 27 | Final commit and submit | Khalid | 0.5 | 26 |

Time estimate: about 30 hours of work left, or about 37 hours with a 25% buffer. With six of us that fits, but tasks 8 to 12 and 19 have to happen one after the other (about 10 hours), so Aritha starts the dashboard with dummy data and Sun starts writing the scoring logic early so nobody is waiting.

## 6. Timeline

Day 1 (Wednesday, opening night): scope, roles, problem statement, dataset chosen, repo set up, first architecture draft. Done.

Day 2 (Thursday):
- 8:30-9:30: learn about CI/CD as a team
- 9:30 onwards: Snowflake ready, start loading data
- 1:00pm: stand-up, data should be cleaned and in staging
- 3:30pm: check-in, every pipe should have a score showing in the app. If not, we cut scope.
- End of day: dashboard check and feature freeze

We'll do a quick stand-up every 2-3 hours (what's done, what's next, anything blocking).

Day 3 (Friday):
- 8:30-9:30: bug fixes and documentation
- 9:30-10:45: finish slides and practise
- 10:45-11:15: final commit and submit (leaving 15 minutes spare)
- After 11:30: present

## 7. Risks

| Risk | What we'll do | Owner |
|---|---|---|
| Someone is unavailable | Shared documentation, and at least two people know each area | Everyone |
| Trial credits run out | Credit limit on the warehouse, smallest warehouse size, Terraform to rebuild | Jibin, Khalid |
| Laptop or hardware failure | Push to GitHub often, don't keep work only on one laptop | Everyone |
| Model isn't ready in time for the dashboard | Build the app with dummy data, use the simple score if ML isn't ready | Karlo, Khalid |
| Results look too good because of future data sneaking in | Only use past data for features, test on later years | Sun |
| Permission errors in Snowflake | Always build tables using the LEAK_ENGINEER role | Jibin |
| Cortex AI not available on the trial | AI summaries are optional, the score doesn't depend on them | Khalid |
| Running out of time on Friday | Feature freeze Thursday night, submit by 11:15 | Khalid |

## 8. Assumptions

Data:
- Break records before 1997 are patchy, so we mainly rely on 1997 onwards
- The pipe ID in the breaks file matches the pipe ID in the water mains file
- Breaks dated before a pipe was installed belong to an older pipe that was replaced, so we leave them out
- The "Asset Size (cm)" column is actually in millimetres

Platform:
- We stay within the Snowflake trial credits using one small warehouse
- Streamlit is available in our Snowflake account

Business:
- Planners care most about which pipes are likely to break, then how bad the break would be
- Missing a real break is worse than one extra inspection

## 9. Deliverables

| Deliverable | Owner |
|---|---|
| Project plan | Karlo, Khalid |
| Architecture diagram | Everyone |
| Data model | Wayne |
| Technical design | Everyone |
| Working prototype | Wayne, Aritha, Sun |
| Limitations, recommendations, learnings | Karlo |
| Presentation | Karlo, Khalid |
| Code on GitHub | Everyone |
| Testing results, task board, future plans (recommended) | Karlo |

We keep track of our decisions and the reasons for them in [decision_log.md](decision_log.md).
