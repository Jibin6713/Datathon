# Decision log

**Owner:** Karlo. Add a row whenever the team makes a choice a judge might ask "why?" about.

| When | Decision | Why | Alternatives considered | Who |
|---|---|---|---|---|
| Hour 0 | Set up Snowflake by hand, adopt it with Terraform later | Unblock the whole team immediately; codify once stable | Terraform first (team blocked ~1h) | Jibin |
| Hour 0 | One database (`LEAK_DB`), one XSMALL warehouse | 1-day build, trial credits; cost attributed with query tags | DEV/PROD split, warehouse per workload | Jibin |
| Hour 0 | 3 roles: ENGINEER / ANALYST / ADMIN | Least privilege without slowing anyone down | Per-person or per-schema roles | Jibin |
| | | | | |
