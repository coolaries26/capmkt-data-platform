# D1: WSL and tooling (run in PowerShell, not Ubuntu)
echo " ---- WSL and tooling ---- "
wsl -l -v                       # Ubuntu-24.04 must show VERSION 2

# D2: Python and tools (run from the repo root)
echo " ---- Python and tools ---- "
uv run python --version         # 3.11.x
uv run dbt --version
echo " ---- pytest ---- "
uv run pytest -q
echo "db Trigger test ---- "
psql -U capmkt -d capmkt -f ./test/trigger_test.sql
echo " ---- git log ---- "
git log --oneline -10

# D3: database
echo " ---- Database ---- "
psql -h localhost -U capmkt -d capmkt -c "\dn"                  # 10 schemas
psql -h localhost -U capmkt -d capmkt -c "\d+ raw.bhavcopy_cm"  # partitions, indexes, triggers
psql -h localhost -U capmkt -d capmkt -c "\dt audit.*" 
psql -h localhost -U capmkt -d capmkt -c "\dt ref.*" 
psql -h localhost -U capmkt -d capmkt -c "\dt raw.*" 