# Docker and Kubernetes Lab (10 working days)

**Window:** Thu 19 Nov to Wed 2 Dec 2026 | **Effort:** about 3 hours/day | **Repo:** `capmkt-data-platform`

By Day 10 you will have containerised the pipeline, run it in a local Kubernetes cluster
(Postgres, a scheduled ingest job, a dashboard), debugged real failures, and packaged
everything as a Helm chart. Every day ends with a deliverable in git and a "break it" drill,
because breaking things on purpose is what turns "I followed a tutorial" into "I can run this".

| Days | Part | Theme |
| ---- | ---- | ----- |
| L1 to L5 | A: Docker | Fundamentals, compose, Dockerfile, pipeline in compose, dashboard, scan, CI, registry |
| L6 to L10 | B: Kubernetes | Cluster basics, Postgres StatefulSet, Job and CronJob, dbt and Streamlit with a debugging drill, Helm |

---

## 0. Ground rules

**Daily rhythm (about 3 hours):**
30 min read the docs for the day, 100 min build, 30 min "break it", 20 min daily log, PR and merge.

**Daily git flow:** branch `feature/lNN-topic`, small commits, PR, squash merge. Tag `v0.1.0`
at the end of L5 and `v0.2.0` at the end of L10.

**Daily log** (`docs/daily_log/YYYY-MM-DD.md`):

```
# Day LNN: <topic>
Done:
Blocked / not done:
Commands worth remembering:
What broke and how I found out:
One thing I can now explain:
Tomorrow:
```

**Assumptions:** Windows 10/11 with WSL2 Ubuntu 24.04, systemd enabled (`/etc/wsl.conf`
has `[boot] systemd=true`), repo cloned under `~/projects` (never under `/mnt/c`), 16 GB RAM
(set `memory=6GB` in `.wslconfig`; kind plus Docker is hungrier than the earlier plan).

**Do not get blocked by Phase 2 code.** The real ingest and dbt models are Phase 2 work.
This lab uses two stand-in commands (`healthcheck` and `load-sample`, defined on Day 4) and a
stand-in dashboard (Day 5). When your real `ingest` command works later, swap it in; the
container and Kubernetes parts do not change.

**Module name:** your repo shows `src/capmkt_data_platform`, so commands use
`capmkt_data_platform`. If your package folder is named differently, adjust the Dockerfile
entrypoint and imports.

---

## Part A: Docker

### L1 (Thu 19 Nov): Hygiene and Docker fundamentals

**Goal:** a clean repo and a working mental model of images, containers and volumes.

**1. Repo hygiene (30 min).** `.env` is tracked in your repo and `logs/` is committed.

```bash
git switch main && git pull && git switch -c feature/l01-docker-basics
git rm --cached .env && git rm -r --cached logs
printf '.env\nlogs/\ndata/\n' >> .gitignore
cp .env .env.example        # then edit .env.example: replace real values with placeholders
git add .gitignore .env.example && git commit -m "chore(security): stop tracking .env and logs"
```

Rotate the database password you used. The old value stays in git history; for a throwaway local
password that is acceptable, but note it in your daily log as a lesson.

**2. Install Docker Engine in WSL (30 min).**

```bash
sudo systemctl disable --now postgresql 2>/dev/null || true   # free port 5432 if native Postgres exists
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
docker run --rm hello-world
docker version && docker info | head -20
```

(Docker Desktop with WSL integration also works. Use one or the other, not both.)

**3. Core command drill (60 min).** Use port 5433 so nothing collides later.

```bash
docker run -d --name pg-lab -e POSTGRES_PASSWORD=lab -p 5433:5432 \
  -v pg-lab-data:/var/lib/postgresql/data postgres:16
docker ps && docker logs -f pg-lab            # Ctrl+C to stop following
docker exec -it pg-lab psql -U postgres -c "create table t(i int); insert into t values (1);"
docker rm -f pg-lab                           # remove the container...
docker run -d --name pg-lab -e POSTGRES_PASSWORD=lab -p 5433:5432 \
  -v pg-lab-data:/var/lib/postgresql/data postgres:16
docker exec -it pg-lab psql -U postgres -c "select * from t;"   # ...the data survived
docker rm -f pg-lab && docker volume rm pg-lab-data             # now it is really gone
docker inspect <container>; docker stats --no-stream; docker system df
```

**4. Write in your own words (30 min, in `docs/lab/L01.md`):** image vs container, what a layer
is, volume vs bind mount, what `-p 5433:5432` means, why `:latest` is a bad production tag.

**Break it:** run the Postgres container without `-v`, insert a row, `docker rm -f`, start again.
The data is gone. Write down why.

**Deliverable:** `.env` untracked, `.env.example` committed, `docs/lab/L01.md`.
**Interview check:** What is the difference between an image and a container? Where does container data live and when is it lost?

---

### L2 (Fri 20 Nov): Postgres in Docker Compose

**Goal:** the database from the design plan, reproducible with one command.

**1. Prepare the DDL.** Copy your DDL files into `docker/initdb/`, **except** the script that
creates the role and databases (the `POSTGRES_*` variables do that). Add one extra file now so
Airflow can reuse the server later:

```bash
mkdir -p docker/initdb
cp db_design/01_schemas.sql db_design/02_audit_tables.sql db_design/03_raw_tables.sql \
   db_design/04_ref_tables.sql db_design/05_triggers.sql docker/initdb/   # adjust to your real file names
echo "CREATE DATABASE airflow_meta;" > docker/initdb/00_airflow_meta.sql
```

Scripts in `/docker-entrypoint-initdb.d` run in name order, once, when the data directory is empty.

**2. `docker-compose.yml`:**

```yaml
name: capmkt

services:
  postgres:
    image: postgres:16
    container_name: capmkt-postgres
    environment:
      POSTGRES_USER: ${PGUSER}
      POSTGRES_PASSWORD: ${PGPASSWORD}
      POSTGRES_DB: ${PGDATABASE}
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./docker/initdb:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 3s
      retries: 10
      start_period: 10s
    restart: unless-stopped

volumes:
  pgdata:
```

**3. `Makefile`** (recipes must be indented with a TAB):

```make
.PHONY: db-up db-down db-reset build health

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

db-reset:
	docker compose down -v && docker compose up -d postgres

build:
	docker build -t capmkt:dev .

health:
	docker compose run --rm app healthcheck
```

**4. Verify.**

```bash
make db-up && docker compose ps               # wait for "healthy"
docker compose exec postgres psql -U "$PGUSER" -d "$PGDATABASE" -c '\dn'
```

Test your three triggers by hand (future trade date rejected, UPDATE blocked, symbol upper-cased).

**Break it:** edit a file in `docker/initdb/`, then `docker compose down && docker compose up -d`.
Nothing changes, because init scripts only run on an empty volume. Fix it with `make db-reset`
and explain the difference between `down` and `down -v`.

**Deliverable:** compose file, Makefile, `docker/initdb/`, trigger test output in the daily log.
**Interview check:** Why a healthcheck, and why a named volume instead of a bind mount for database files?

---

### L3 (Mon 23 Nov): The pipeline image

**Goal:** a small, cached, non-root image built with uv.

**1. Stand-in CLI.** Put this in `src/capmkt_data_platform/cli.py` (merge with your existing CLI if one exists):

```python
"""Minimal CLI used by the container lab."""

import os
from datetime import date

import psycopg
import typer

app = typer.Typer(no_args_is_help=True)


def _dsn() -> str:
    return (
        f"host={os.environ.get('PGHOST', 'localhost')} "
        f"port={os.environ.get('PGPORT', '5432')} "
        f"dbname={os.environ['PGDATABASE']} "
        f"user={os.environ['PGUSER']} "
        f"password={os.environ['PGPASSWORD']}"
    )


@app.command()
def healthcheck() -> None:
    """Connect to Postgres, print schema and row counts. Exit 1 on failure."""
    try:
        with psycopg.connect(_dsn(), connect_timeout=5) as conn, conn.cursor() as cur:
            cur.execute(
                "select count(*) from information_schema.schemata "
                "where schema_name in ('raw','audit','ref','stg','core')"
            )
            schemas = cur.fetchone()[0]
            cur.execute("select count(*) from raw.bhavcopy_cm")
            rows = cur.fetchone()[0]
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"UNHEALTHY: {exc}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"OK schemas={schemas} raw.bhavcopy_cm rows={rows}")


@app.command("load-sample")
def load_sample() -> None:
    """Stand-in ingest job: idempotently loads 3 sample rows for a fixed past date."""
    sample_date = date(2026, 11, 13)
    rows = [
        ("AAA", 100, 110, 95, 105, 100),
        ("BBB", 50, 52, 49, 51, 50),
        ("CCC", 200, 210, 198, 205, 199),
    ]
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute("delete from raw.bhavcopy_cm where trade_date = %s", (sample_date,))
        cur.execute(
            "update audit.ingestion_log set status = 'SUPERSEDED' "
            "where dataset = 'sample' and trade_date = %s and status = 'SUCCESS'",
            (sample_date,),
        )
        cur.execute(
            "insert into audit.ingestion_log (dataset, trade_date, source_url, status, rows_loaded, finished_at) "
            "values ('sample', %s, 'local://sample', 'SUCCESS', %s, now()) returning load_id",
            (sample_date, len(rows)),
        )
        load_id = cur.fetchone()[0]
        cur.executemany(
            "insert into raw.bhavcopy_cm (load_id, trade_date, symbol, series, open_price, high_price, "
            "low_price, close_price, prev_close_price) values (%s, %s, %s, 'EQ', %s, %s, %s, %s, %s)",
            [(load_id, sample_date, *r) for r in rows],
        )
    typer.echo(f"loaded {len(rows)} sample rows, load_id={load_id}")


if __name__ == "__main__":
    app()
```

**2. `.dockerignore`** (what must never enter the build context):

```
.git
.venv
.env
.env.*
!.env.example
data/
logs/
**/__pycache__
*.pyc
*.zip
*.parquet
.pytest_cache
.ruff_cache
dbt/target
dbt/dbt_packages
dbt/logs
docs/
k8s/
charts/
```

**3. `Dockerfile`:**

```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.11-slim-bookworm AS builder
# Pin to the version printed by `uv --version` on your machine
COPY --from=ghcr.io/astral-sh/uv:0.X.Y /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Dependency layer: rebuilt only when pyproject.toml or uv.lock change
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Project layer: rebuilt on every source change
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


FROM python:3.11-slim-bookworm AS runtime
RUN groupadd --system --gid 10001 app \
 && useradd  --system --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DBT_PROFILES_DIR=/app/dbt
USER 10001
ENTRYPOINT ["python", "-m", "capmkt_data_platform.cli"]
CMD ["--help"]
```

The numeric `USER 10001` matters: Kubernetes can only verify `runAsNonRoot` against a numeric UID.

**4. Build and inspect.**

```bash
make build
docker run --rm capmkt:dev                    # prints CLI help
docker images capmkt; docker history capmkt:dev
docker run --rm --entrypoint id capmkt:dev    # uid=10001, not root
```

**5. Cache experiment.** Rebuild after (a) editing a `.py` file and (b) adding a dependency
with `uv add`. Record which layers were reused each time and how long each build took.

**Break it (security):** temporarily delete `.env` from `.dockerignore`, rebuild, then run
`docker run --rm --entrypoint ls capmkt:dev -la /app` and see the secrets file inside the image.
Restore the ignore rule. Also write `Dockerfile.naive` (single stage, `python:3.11`, plain `pip install`)
and compare image sizes in your notes.

**Deliverable:** `Dockerfile`, `.dockerignore`, `cli.py`, size and cache notes in `docs/lab/L03.md`.
**Interview check:** Why multi-stage? Why order `COPY` of lock files before source? Why a non-root user?

---

### L4 (Tue 24 Nov): The pipeline inside Compose

**Goal:** run the pipeline as a container that talks to the database container.

Add to `docker-compose.yml`:

```yaml
  app:
    build: .
    image: capmkt:dev
    profiles: ["tools"]
    env_file: .env
    environment:
      PGHOST: postgres          # the service name, not localhost
    depends_on:
      postgres:
        condition: service_healthy
```

(`environment` overrides the `PGHOST=localhost` in `.env`.)

```bash
make db-up
docker compose run --rm app healthcheck           # OK schemas=5 raw.bhavcopy_cm rows=0
docker compose run --rm app load-sample
docker compose run --rm app load-sample           # run twice: still 3 rows (idempotent)
docker compose run --rm app healthcheck           # rows=3
docker compose run --rm --entrypoint dbt app debug   # "All checks passed" proves dbt can reach the DB
```

If `dbt debug` fails on the profile, check that `dbt/profiles.yml` reads the `PG*` environment variables.

**Break it:**
1. `docker compose run --rm -e PGHOST=localhost app healthcheck` fails: inside a container,
   `localhost` is the container itself. Explain the Docker network and service DNS.
2. `docker compose stop postgres && docker compose run --rm --no-deps app healthcheck` fails fast.
   Note the difference between `depends_on` (start order and health) and retry logic in your code.

**Deliverable:** working `app` service, `make health`, and a short note on container networking in `docs/lab/L04.md`.
**Interview check:** How do containers find each other in compose? What does `depends_on: service_healthy` guarantee, and what does it not?

---

### L5 (Wed 25 Nov): Dashboard, image security, CI and registry

**Goal:** a second service from the same image, a scanned image, and an automated build.

**1. Stand-in dashboard**, `dashboards/streamlit_app.py`:

```python
import os

import pandas as pd
import psycopg
import streamlit as st

st.set_page_config(page_title="capmkt", layout="wide")
st.title("Capital Markets Data Platform")


@st.cache_data(ttl=30)
def query(sql: str) -> pd.DataFrame:
    dsn = (
        f"host={os.environ.get('PGHOST', 'localhost')} port={os.environ.get('PGPORT', '5432')} "
        f"dbname={os.environ['PGDATABASE']} user={os.environ['PGUSER']} password={os.environ['PGPASSWORD']}"
    )
    with psycopg.connect(dsn, connect_timeout=5) as conn, conn.cursor() as cur:
        cur.execute(sql)
        cols = [d.name for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


st.subheader("Ingestion log")
st.dataframe(
    query(
        "select load_id, dataset, trade_date, status, rows_loaded, finished_at "
        "from audit.ingestion_log order by load_id desc limit 20"
    )
)
st.subheader("Rows per trade date")
st.bar_chart(
    query(
        "select trade_date, count(*) as rows from raw.bhavcopy_cm group by 1 order by 1"
    ),
    x="trade_date",
    y="rows",
)
```

**2. Compose service:**

```yaml
  streamlit:
    image: capmkt:dev
    depends_on:
      postgres:
        condition: service_healthy
    env_file: .env
    environment:
      PGHOST: postgres
    entrypoint: ["streamlit", "run", "dashboards/streamlit_app.py",
                 "--server.port=8501", "--server.address=0.0.0.0"]
    ports:
      - "8501:8501"
    mem_limit: 512m
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"]
      interval: 10s
      timeout: 3s
      retries: 5
    restart: unless-stopped
```

`docker compose up -d streamlit` then open `http://localhost:8501` from Windows.
The slim image has no `curl`, which is why the healthcheck uses Python.

**3. Scan the image** (run the scanner as a container, no install):

```bash
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest \
  image --severity HIGH,CRITICAL capmkt:dev
```

Record what it finds. Fix what a base-image bump or dependency update fixes; for the rest, write
down why it is not exploitable here or what you would do in a real team.

**4. Tag and publish via CI**, `.github/workflows/ci.yml` (confirm the latest major version of each action on its GitHub page):

```yaml
name: ci
on:
  push:
    branches: [main]
    tags: ["v*"]
  pull_request:

permissions:
  contents: read
  packages: write

jobs:
  image:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        if: startsWith(github.ref, 'refs/tags/v')
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository }}
          tags: |
            type=semver,pattern={{version}}
            type=sha
      - uses: docker/build-push-action@v6
        with:
          context: .
          push: ${{ startsWith(github.ref, 'refs/tags/v') }}
          tags: ${{ steps.meta.outputs.tags }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

Pull requests build only; tags push `0.1.0` and a SHA tag to GHCR. Tag `v0.1.0` at the end of the day.

**Break it:** set `mem_limit: 50m`, recreate the service, and watch it die.
`docker inspect capmkt-streamlit-1 --format '{{.State.OOMKilled}}'` prints `true`. Restore 512m.

**Deliverable:** dashboard, compose service, Trivy notes, green CI run, tag `v0.1.0`.
**Interview check:** Why pin base images and tag by version or SHA? What does an image scan tell you and not tell you?

**Week 1 checkpoint (Fri 27 Nov is on the Kubernetes side; take 15 minutes now):** with only
`make db-up && docker compose run --rm app load-sample && docker compose up -d streamlit`,
can someone else run your stack? If not, fix the README quick start before moving on.

---

## Part B: Kubernetes

### L6 (Thu 26 Nov): Cluster basics with kind

**Goal:** comfortable with the cluster, pods, Deployments and `kubectl`.

**1. Install the tools (30 min).**

```bash
# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
# kind
curl -Lo ./kind https://github.com/kubernetes-sigs/kind/releases/latest/download/kind-linux-amd64
sudo install -m 0755 kind /usr/local/bin/kind
# helm (v3 or v4: everything in this lab works with both)
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
# convenience
echo 'alias k=kubectl; source <(kubectl completion bash); complete -F __start_kubectl k' >> ~/.bashrc
```

**2. `k8s/kind-config.yaml` and cluster:**

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: capmkt
nodes:
  - role: control-plane
  - role: worker
  - role: worker
```

```bash
kind create cluster --config k8s/kind-config.yaml
kubectl cluster-info --context kind-capmkt
kubectl get nodes -o wide && kubectl -n kube-system get pods
```

Add `kind-up` and `kind-down` targets to the Makefile (`kind create cluster --config ...` / `kind delete cluster --name capmkt`).

**3. Object drill (90 min).**

```bash
kubectl create namespace scratch
kubectl -n scratch create deployment web --image=nginx:1.27 --replicas=2
kubectl -n scratch get pods -o wide
kubectl -n scratch expose deployment web --port=80
kubectl -n scratch port-forward svc/web 8080:80          # http://localhost:8080
kubectl -n scratch scale deployment web --replicas=4
kubectl -n scratch set image deployment/web nginx=nginx:1.27-alpine
kubectl -n scratch rollout status deployment/web
kubectl -n scratch rollout history deployment/web
kubectl -n scratch get deployment web -o yaml            # read it
kubectl explain deployment.spec.strategy                 # built-in docs
kubectl -n scratch create deployment x --image=nginx --dry-run=client -o yaml   # generate manifests
```

Draw, from memory, the control plane (API server, etcd, scheduler, controller manager) and
node components (kubelet, container runtime, kube-proxy, CNI). Then verify against
`kubectl -n kube-system get pods`.

**Break it:**
1. `kubectl -n scratch delete pod <one-pod>`: it comes back. Say which controller did that.
2. `kubectl -n scratch set image deployment/web nginx=nginx:does-not-exist`: watch
   `ImagePullBackOff`, read `kubectl -n scratch describe pod <pod>` (Events), then
   `kubectl -n scratch rollout undo deployment/web`.

Clean up: `kubectl delete namespace scratch`.

**Deliverable:** `k8s/kind-config.yaml`, `kind-up/down`, `docs/lab/L06.md` (diagram plus the two failures explained).
**Interview check:** What happens, step by step, when you run `kubectl apply` on a Deployment? Pod vs ReplicaSet vs Deployment?

---

### L7 (Fri 27 Nov): Postgres on Kubernetes (StatefulSet, Secret, ConfigMap, PVC)

**Goal:** stateful workload done properly, with configuration kept out of images.

**1. Files under `k8s/base/`.**

`00-namespace.yaml`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: capmkt
```

`10-config.yaml` (non-secret settings):

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: capmkt-config
  namespace: capmkt
data:
  PGHOST: postgres
  PGPORT: "5432"
```

`20-postgres.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: postgres-headless
  namespace: capmkt
spec:
  clusterIP: None
  selector: {app: postgres}
  ports:
    - {name: pg, port: 5432}
---
apiVersion: v1
kind: Service
metadata:
  name: postgres
  namespace: capmkt
spec:
  selector: {app: postgres}
  ports:
    - {name: pg, port: 5432, targetPort: pg}
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: capmkt
spec:
  serviceName: postgres-headless
  replicas: 1
  selector:
    matchLabels: {app: postgres}
  template:
    metadata:
      labels: {app: postgres}
    spec:
      containers:
        - name: postgres
          image: postgres:16
          ports:
            - {name: pg, containerPort: 5432}
          env:
            - name: POSTGRES_USER
              valueFrom: {secretKeyRef: {name: capmkt-db, key: PGUSER}}
            - name: POSTGRES_PASSWORD
              valueFrom: {secretKeyRef: {name: capmkt-db, key: PGPASSWORD}}
            - name: POSTGRES_DB
              valueFrom: {secretKeyRef: {name: capmkt-db, key: PGDATABASE}}
            - name: PGDATA
              value: /var/lib/postgresql/data/pgdata
          readinessProbe:
            exec:
              command: ["sh", "-c", "pg_isready -U $POSTGRES_USER -d $POSTGRES_DB"]
            initialDelaySeconds: 5
            periodSeconds: 5
          livenessProbe:
            exec:
              command: ["sh", "-c", "pg_isready -U $POSTGRES_USER -d $POSTGRES_DB"]
            initialDelaySeconds: 30
            periodSeconds: 10
          resources:
            requests: {cpu: 100m, memory: 256Mi}
            limits: {memory: 512Mi}
          volumeMounts:
            - {name: data, mountPath: /var/lib/postgresql/data}
            - {name: initdb, mountPath: /docker-entrypoint-initdb.d, readOnly: true}
      volumes:
        - name: initdb
          configMap:
            name: postgres-initdb
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 2Gi
```

`secret.example.yaml` (shape only, placeholder values, safe to commit):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: capmkt-db
  namespace: capmkt
type: Opaque
stringData:
  PGUSER: capmkt
  PGPASSWORD: change_me
  PGDATABASE: capmkt
```

**2. Apply.** The real Secret and the init ConfigMap are created from existing files, so
`docker/initdb/` stays the single source of truth for the DDL:

```bash
kubectl apply -f k8s/base/00-namespace.yaml
set -a; source .env; set +a
kubectl -n capmkt create secret generic capmkt-db \
  --from-literal=PGUSER="$PGUSER" --from-literal=PGPASSWORD="$PGPASSWORD" --from-literal=PGDATABASE="$PGDATABASE"
kubectl -n capmkt create configmap postgres-initdb --from-file=docker/initdb/
kubectl apply -f k8s/base/10-config.yaml -f k8s/base/20-postgres.yaml
kubectl -n capmkt get pods -w
kubectl -n capmkt exec -it postgres-0 -- psql -U "$PGUSER" -d "$PGDATABASE" -c '\dn'
kubectl -n capmkt get pvc,svc,sts
```

Note that a Secret is base64-encoded, not encrypted: `kubectl -n capmkt get secret capmkt-db -o jsonpath='{.data.PGPASSWORD}' | base64 -d`.
Write down what that means for how you treat Secrets in git and in a real cluster.

**Break it:**
1. Create a marker table, then `kubectl -n capmkt delete pod postgres-0`. The pod returns and the table is still there. Why?
2. `kubectl -n capmkt scale sts postgres --replicas=0`, then `kubectl -n capmkt delete pvc data-postgres-0`, then scale back to 1.
   The database is empty. Explain what a PVC is and how StatefulSet differs from Deployment for storage.
3. Edit the init ConfigMap and delete the pod: the new script is **not** re-run. Compare with L2.

**Deliverable:** `k8s/base/*`, Makefile target `k8s-apply`, `docs/lab/L07.md`.
**Interview check:** StatefulSet vs Deployment? What is a headless service for? Why are probes separate for readiness and liveness?

---

### L8 (Mon 30 Nov): Job and CronJob for the pipeline

**Goal:** run the pipeline image as a batch workload, on a schedule, with sane limits.

**1. Get the image into kind.** kind nodes cannot see your local Docker images until you load them.
Use a fixed tag, never `latest`:

```bash
docker build -t capmkt:0.1.0 .
kind load docker-image capmkt:0.1.0 --name capmkt
```

**2. One-off Job**, `k8s/base/30-job-load-sample.yaml`:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: load-sample
  namespace: capmkt
spec:
  backoffLimit: 2
  activeDeadlineSeconds: 300
  template:
    spec:
      restartPolicy: Never
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
      containers:
        - name: ingest
          image: capmkt:0.1.0
          imagePullPolicy: IfNotPresent
          args: ["load-sample"]
          envFrom:
            - configMapRef: {name: capmkt-config}
            - secretRef: {name: capmkt-db}
          resources:
            requests: {cpu: 100m, memory: 128Mi}
            limits: {memory: 256Mi}
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          volumeMounts:
            - {name: tmp, mountPath: /tmp}
      volumes:
        - name: tmp
          emptyDir: {}
```

```bash
kubectl apply -f k8s/base/30-job-load-sample.yaml
kubectl -n capmkt get jobs,pods
kubectl -n capmkt logs job/load-sample
```

Note how `command` and `args` map to Docker: `command` replaces `ENTRYPOINT`, `args` replaces `CMD`.
Here we only set `args`, so the image's Python entrypoint stays and runs `load-sample`.

**3. CronJob**, `k8s/base/31-cronjob-ingest.yaml`: same pod template, wrapped:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: capmkt-ingest
  namespace: capmkt
spec:
  schedule: "30 19 * * 1-5"
  timeZone: "Asia/Kolkata"
  concurrencyPolicy: Forbid
  startingDeadlineSeconds: 3600
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 2
      activeDeadlineSeconds: 900
      ttlSecondsAfterFinished: 86400
      template:
        spec:
          # copy the pod spec from the Job above (restartPolicy, securityContext, containers, volumes)
```

```bash
kubectl apply -f k8s/base/31-cronjob-ingest.yaml
kubectl -n capmkt get cronjob                      # shows schedule and timezone
kubectl -n capmkt create job --from=cronjob/capmkt-ingest manual-1    # trigger without waiting
kubectl -n capmkt logs job/manual-1
```

Write a sentence for each field: `concurrencyPolicy`, `startingDeadlineSeconds`, `backoffLimit`,
`activeDeadlineSeconds`, `ttlSecondsAfterFinished`. When your real ingest exists, the args become
`["ingest", "--dataset", "bhavcopy_cm", "--date", "today"]` (support `today` in the CLI).

**Break it (three drills, one at a time):**
1. **Wrong credentials:** recreate the Secret with a wrong `PGPASSWORD`, run a Job, and find the
   error with `kubectl logs`. Restore it.
2. **OOMKilled:** set `limits.memory: 20Mi` and run again. `kubectl -n capmkt describe pod <pod>`
   shows `Reason: OOMKilled` and `Exit Code: 137`. Explain requests vs limits.
3. **Image pull failure:** change the tag to `capmkt:latest` or a tag you did not load.
   Observe `ErrImagePull`/`ImagePullBackOff`, and explain `imagePullPolicy` and why kind needs `kind load`.

**Deliverable:** Job and CronJob manifests, three drills written up in `docs/lab/debug-log.md` (start this file today).
**Interview check:** Job vs CronJob vs Deployment? What does exit code 137 mean? Why `concurrencyPolicy: Forbid` for an ingest?

---

### L9 (Tue 1 Dec): dbt Job, Streamlit Deployment, and the debugging drill

**Goal:** a multi-component app on Kubernetes and the confidence to diagnose it when it breaks.

**1. dbt as a Job**, `k8s/base/32-job-dbt-debug.yaml`: copy the L8 Job, set
`command: ["dbt"]` and `args: ["debug", "--project-dir", "dbt"]`, add a `/tmp` emptyDir and
`env: [{name: DBT_LOG_PATH, value: /tmp/dbt-logs}, {name: DBT_TARGET_PATH, value: /tmp/dbt-target}]`
(dbt writes logs and artifacts, and the root filesystem is read-only). Run it and read the logs.
Once Phase 2 models exist, switch the args to `["build", "--project-dir", "dbt"]`.

**2. Streamlit Deployment and Service**, `k8s/base/40-streamlit.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: streamlit
  namespace: capmkt
spec:
  replicas: 1
  selector:
    matchLabels: {app: streamlit}
  template:
    metadata:
      labels: {app: streamlit}
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
      containers:
        - name: streamlit
          image: capmkt:0.1.0
          imagePullPolicy: IfNotPresent
          command: ["streamlit"]
          args: ["run", "dashboards/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
          ports:
            - {name: http, containerPort: 8501}
          envFrom:
            - configMapRef: {name: capmkt-config}
            - secretRef: {name: capmkt-db}
          readinessProbe:
            httpGet: {path: /_stcore/health, port: http}
            initialDelaySeconds: 5
            periodSeconds: 5
          livenessProbe:
            httpGet: {path: /_stcore/health, port: http}
            initialDelaySeconds: 20
            periodSeconds: 10
          resources:
            requests: {cpu: 100m, memory: 256Mi}
            limits: {memory: 512Mi}
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
---
apiVersion: v1
kind: Service
metadata:
  name: streamlit
  namespace: capmkt
spec:
  selector: {app: streamlit}
  ports:
    - {name: http, port: 80, targetPort: http}
```

```bash
kubectl apply -f k8s/base/40-streamlit.yaml
kubectl -n capmkt port-forward svc/streamlit 8501:80       # http://localhost:8501
```

(Streamlit writes small files under the home directory. If it complains about a read-only
filesystem, leave `readOnlyRootFilesystem` off for this Deployment and note why.)

**3. The debugging drill (the most valuable 90 minutes of the lab).** Inject each fault, then
diagnose it **before** looking at the table's last column. For each, record in
`docs/lab/debug-log.md`: symptom, commands you ran, root cause, fix.

| # | Inject | What you should see | Where to look |
| - | ------ | ------------------- | ------------- |
| 1 | `kubectl -n capmkt set image deploy/streamlit streamlit=capmkt:9.9.9` | `ImagePullBackOff` | `describe pod` Events |
| 2 | Patch the Deployment so `secretRef.name` is `missing-secret` | `CreateContainerConfigError` | `describe pod` Events |
| 3 | `kubectl -n capmkt patch cm capmkt-config --type merge -p '{"data":{"PGHOST":"postgress"}}'` then `rollout restart` | App errors on DNS lookup | `kubectl logs`, `kubectl exec ... getent hosts postgress` |
| 4 | Change the readiness probe port to 9999 | Pod `Running` but `0/1` Ready, Service has no endpoints | `kubectl get endpoints streamlit`, `describe pod` |
| 5 | Set `requests.cpu: "64"` | Pod stays `Pending` | `describe pod`: `Insufficient cpu` |
| 6 | `kubectl -n capmkt scale sts postgres --replicas=0` | Dashboard errors, healthy-looking pods | `kubectl logs`, `get sts`, ordering of dependencies |

Always start with: `kubectl get pods`, `kubectl describe pod`, `kubectl logs --previous`,
`kubectl get events --sort-by=.lastTimestamp`, `kubectl get endpoints`. Restore each fault with
`kubectl apply -f` of the original manifest before starting the next.

**Stretch:** install `ingress-nginx` in kind (needs `extraPortMappings` in the kind config) and
expose Streamlit through an Ingress instead of port-forward.

**Deliverable:** dbt Job, Streamlit manifests, six fault write-ups in `docs/lab/debug-log.md`.
**Interview check:** A pod is `Running` but gets no traffic. Walk me through diagnosing it. What is the difference between a Service and an Endpoint?

---

### L10 (Wed 2 Dec): Helm chart and wrap-up

**Goal:** package it, deploy it from nothing, and be able to explain all of it.

**1. Chart skeleton** under `charts/capmkt/`:

`Chart.yaml`:

```yaml
apiVersion: v2
name: capmkt
description: Capital markets data platform
type: application
version: 0.1.0
appVersion: "0.1.0"
```

`values.yaml`:

```yaml
image:
  repository: capmkt
  tag: "0.1.0"
  pullPolicy: IfNotPresent

existingSecret: capmkt-db     # created out of band, never in values or git

config:
  PGHOST: postgres
  PGPORT: "5432"

postgres:
  enabled: true
  storage: 2Gi

ingest:
  enabled: true
  schedule: "30 19 * * 1-5"
  timeZone: Asia/Kolkata
  args: ["load-sample"]
  resources:
    requests: {cpu: 100m, memory: 128Mi}
    limits: {memory: 256Mi}

streamlit:
  enabled: true
  replicas: 1
```

`templates/cronjob-ingest.yaml` (one worked example):

```yaml
{{- if .Values.ingest.enabled }}
apiVersion: batch/v1
kind: CronJob
metadata:
  name: {{ .Release.Name }}-ingest
  namespace: {{ .Release.Namespace }}
spec:
  schedule: {{ .Values.ingest.schedule | quote }}
  timeZone: {{ .Values.ingest.timeZone | quote }}
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      backoffLimit: 2
      activeDeadlineSeconds: 900
      template:
        spec:
          restartPolicy: Never
          securityContext:
            runAsNonRoot: true
            runAsUser: 10001
          containers:
            - name: ingest
              image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
              imagePullPolicy: {{ .Values.image.pullPolicy }}
              args: {{ toJson .Values.ingest.args }}
              envFrom:
                - configMapRef:
                    name: {{ .Release.Name }}-config
                - secretRef:
                    name: {{ .Values.existingSecret }}
              resources:
                {{- toYaml .Values.ingest.resources | nindent 16 }}
{{- end }}
```

Convert the rest yourself: `configmap.yaml` (from `config:`), `postgres.yaml`
(wrapped in `{{- if .Values.postgres.enabled }}`), `streamlit.yaml`. Keep the Service named
`postgres` so `PGHOST` still resolves. Create the Secret and init ConfigMap exactly as in L7,
since they are deliberately outside the chart.

**2. Deploy from scratch and exercise the lifecycle:**

```bash
helm lint charts/capmkt
helm template capmkt charts/capmkt -n capmkt | kubectl apply --dry-run=client -f -
kubectl delete namespace capmkt                    # remove the raw-manifest version
kubectl create namespace capmkt                    # then recreate Secret + init ConfigMap (L7 step 2)
helm install capmkt charts/capmkt -n capmkt
helm list -n capmkt
docker build -t capmkt:0.1.1 . && kind load docker-image capmkt:0.1.1 --name capmkt
helm upgrade capmkt charts/capmkt -n capmkt --set image.tag=0.1.1
helm history capmkt -n capmkt
helm rollback capmkt 1 -n capmkt
```

Add `values-dev.yaml` that lowers resource requests and sets a different schedule, and deploy with `-f values-dev.yaml`.
Add `helm-up` and `helm-down` targets to the Makefile.

**3. Wrap-up (45 min):**
- Tick the Phase 1 boxes in the README and fill in the progress tracker.
- Add `docs/architecture.md` with the local architecture diagram and a paragraph on each design choice.
- Rehearse Appendix C aloud, once.
- Tag `v0.2.0`.
- Optional: send a short progress update to the recruiter with the repo link, once the README quick start
  works from a clean clone (test it on a fresh WSL distro or a second machine if you can).

**Deliverable:** `charts/capmkt/`, tag `v0.2.0`, updated README and architecture doc.
**Interview check:** Why Helm over raw manifests? What do `helm template` and `helm upgrade --install` do? How would you manage secrets in a real cluster (external secrets, sealed secrets, cloud secret managers)?

---

## Lab completion checklist

You are done when you can do each of these without notes:

- [ ] Explain image, container, layer, volume, network, and why the Dockerfile is ordered the way it is
- [ ] Show that your image is non-root, small, and free of secrets, and explain the scan results
- [ ] Bring up the stack with compose from a clean clone
- [ ] Draw the Kubernetes control plane and trace what happens on `kubectl apply`
- [ ] Explain StatefulSet, PVC, Service, ConfigMap, Secret, probes, requests and limits
- [ ] Diagnose `ImagePullBackOff`, `CrashLoopBackOff`, `CreateContainerConfigError`, `Pending`, and a not-ready pod
- [ ] Explain CronJob fields and why the ingest uses `concurrencyPolicy: Forbid`
- [ ] Deploy, upgrade and roll back with Helm
- [ ] State honestly what is local-only here and what AWS adds in Phase 3 (managed control plane, IAM, ECR, real storage classes, ingress and load balancers)

---

## Appendix A: Cheat sheet

**Docker:**

```bash
docker ps -a | docker logs -f <c> | docker exec -it <c> sh | docker inspect <c>
docker compose up -d | down | down -v | ps | logs -f <svc> | run --rm <svc> <args>
docker build -t name:tag . | docker history name:tag | docker system prune
```

**kubectl debugging flow:**

```bash
kubectl get pods -o wide
kubectl describe pod <p>                        # Events at the bottom explain most failures
kubectl logs <p> [--previous] [-c <container>]
kubectl get events --sort-by=.lastTimestamp
kubectl get endpoints <svc>                     # empty means selector or readiness problem
kubectl exec -it <p> -- sh
kubectl rollout status|history|undo deployment/<d>
kubectl get <obj> -o yaml | kubectl explain <path>
```

**Common states:** `Pending` = cannot be scheduled (resources, PVC). `ImagePullBackOff` = bad image
name, tag or registry access. `CrashLoopBackOff` = container starts then exits (read previous logs).
`CreateContainerConfigError` = missing Secret or ConfigMap key. `OOMKilled` = hit memory limit.
Running but not Ready = failing readiness probe.

---

## Appendix B: Troubleshooting

| Symptom | Likely cause and fix |
| ------- | -------------------- |
| `port is already allocated` on 5432 | Native Postgres still running in WSL: `sudo systemctl disable --now postgresql` |
| `permission denied` on `/var/run/docker.sock` | Not in the docker group: `sudo usermod -aG docker $USER`, then `newgrp docker` or re-login |
| Init SQL changes ignored | Volume already initialised: `make db-reset` (compose) or recreate the PVC (Kubernetes) |
| `healthcheck` cannot connect from a container | `PGHOST` is `localhost` instead of the service name |
| kind pod stuck in `ErrImageNeverPull` or `ImagePullBackOff` | Image not loaded: `kind load docker-image <tag> --name capmkt`; avoid `:latest` |
| WSL feels slow or runs out of memory | Raise `memory` in `.wslconfig`, `wsl --shutdown`; delete unused images with `docker system prune` |
| `dbt` fails writing logs in a pod | Read-only root filesystem: point `DBT_LOG_PATH` and `DBT_TARGET_PATH` at an emptyDir |
| Helm `invalid ownership metadata` on install | A resource with the same name exists from raw manifests: delete the namespace first |

---

## Appendix C: Interview questions to rehearse

**Docker**
1. Image vs container? What is a layer and how does caching work?
2. Why multi-stage builds? Why a non-root numeric user?
3. How do two containers on one host communicate? What does `-p` do?
4. `CMD` vs `ENTRYPOINT`, and how do Kubernetes `command` and `args` relate to them?
5. How do you keep secrets out of images?

**Kubernetes**
6. What happens when you run `kubectl apply -f deployment.yaml`?
7. Deployment vs StatefulSet vs Job vs CronJob: when do you use each?
8. Readiness vs liveness probes. What goes wrong if a liveness probe is too aggressive?
9. Requests vs limits. What happens at the memory limit? At the CPU limit?
10. A pod is `CrashLoopBackOff`. Walk me through what you do.
11. A pod is `Running` but the Service returns errors. What do you check?
12. How does a pod find the database? What is a Service, and what is a headless Service?
13. How would you run a nightly ingest reliably? (CronJob fields, idempotent loads, alerting on failure)
14. ConfigMap vs Secret. Are Secrets encrypted? What would you use in production?
15. Helm vs Kustomize vs raw manifests?

**Be ready to say honestly:** "I ran this on kind and compose, with my own project. The AWS side
(ECS or EKS, IAM, ECR) is the next phase, and I know the differences are managed control plane,
IAM-based access, cloud storage classes and load balancers."
