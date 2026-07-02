# Deployment Guide — Running This System on a New PC or Device

This guide covers taking the Blade Rocking & Creep Test Management System from
this repository and standing it up on a machine that has never run it before —
whether that's a single demo laptop, a fresh factory PC, or the full two-station
(OH + Assembly) production setup.

Everything runs in Docker, so the target machine does **not** need Python,
Node.js, PostgreSQL, or Redis installed — only Docker itself. The one exception
is the hardware bridge scripts (weighing scale / DTI gauge), which run directly
on Windows — see [Hardware Bridges](#hardware-bridges-weighing-scale--dti-gauge).

> This guide only uses placeholder secrets. The actual `SECRET_KEY` / DB /
> Redis / `OH_SYNC_API_KEY` values currently deployed on this machine's
> `.env`, `.env.oh`, and `.env.assembly` are recorded in `CREDENTIALS.local.md`
> at the repo root — that file is gitignored and must never be committed.

---

## 1. Which setup do you need?

| Setup | When to use | Compose file(s) |
|-------|-------------|------------------|
| **Single machine** | Demo, dev laptop, or a single-PC deployment with everything (DB included) on one box | `docker-compose.yml` |
| **Two-station production** | Real factory floor: OH PC (701 Hanger) hosts the database, Assembly PC (720 Hanger) connects to it over the LAN | `docker-compose.oh.yml` + `docker-compose.oh-ports.yml` (OH PC), `docker-compose.assembly.yml` (Assembly PC) |

If you're just trying the system out, use **Section 3 (Single machine)**.
If you're replicating the real plant deployment, use **Section 4 (Two-station)**.

---

## 2. Prerequisites (any machine)

- **Docker Engine ≥ 24** and **Docker Compose ≥ 2.20**
  - Windows: install [Docker Desktop](https://www.docker.com/products/docker-desktop/) with WSL2 backend enabled.
  - Linux: `sudo apt-get install docker.io docker-compose-plugin` (or follow Docker's official install docs for your distro).
- **Git**, to clone the repository — or a way to copy the project folder over (USB drive / network share), since after the first `docker-compose build` no further internet access is required.
- At least **4 GB RAM** and **10 GB free disk** (PaddleOCR models + Postgres data add up).
- If this machine will run on the plant LAN: know its **static LAN IP** ahead of time (e.g. `192.168.1.50`) — several config values below need it.

---

## 3. Single-machine setup

```bash
# 1. Get the code onto the machine
git clone <your-repo-url> blade-rocking
cd blade-rocking

# 2. Create the environment file
cp .env.example .env
```

Edit `.env` and set, at minimum:

- `SECRET_KEY` — generate with `python3 -c "import secrets; print(secrets.token_hex(32))"` (or `openssl rand -hex 32` if Python isn't installed on this machine)
- `POSTGRES_PASSWORD`
- `REDIS_PASSWORD`
- `CORS_ORIGINS` — include this machine's LAN IP if other devices on the network will access it, e.g. `http://localhost,http://192.168.1.50`

```bash
# 3. Build and start everything
docker-compose build
docker-compose up -d

# 4. Apply database migrations
docker-compose exec backend alembic upgrade head

# 5. (Optional, first time only) seed demo data
docker-compose exec backend python ../scripts/seed_data.py
```

Or use the bundled script, which does all of the above plus health-check waiting:

```bash
./scripts/deploy.sh --fresh        # first time
./scripts/deploy.sh                # subsequent updates
./scripts/deploy.sh --fresh --https  # also generate a self-signed TLS cert
```

**Access:**

| What | URL |
|------|-----|
| Web app | `http://<this-machine-IP>/` |
| API docs | `http://<this-machine-IP>/docs` |

---

## 4. Two-station production setup

### 4.1 OH PC (hosts the database)

```bash
git clone <your-repo-url> blade-rocking   # or copy the folder over
cd blade-rocking
cp .env.oh.example .env.oh
```

Edit `.env.oh`:

- `POSTGRES_PASSWORD` — pick a strong password, you'll need it again on the Assembly PC
- `REDIS_PASSWORD`
- `SECRET_KEY` — generate independently (`python3 -c "import secrets; print(secrets.token_hex(32))"`)
- `OH_SYNC_API_KEY` — generate a shared secret; the Assembly PC must use the **same** value
- `CORS_ORIGINS` — add the Assembly PC's LAN IP if its browser calls the OH API directly

```bash
docker-compose -f docker-compose.oh.yml -f docker-compose.oh-ports.yml build
docker-compose -f docker-compose.oh.yml -f docker-compose.oh-ports.yml up -d
docker-compose -f docker-compose.oh.yml exec oh_backend alembic upgrade head
docker-compose -f docker-compose.oh.yml exec oh_backend python ../scripts/seed_data.py   # first time only
```

The `docker-compose.oh-ports.yml` override is what exposes PostgreSQL's port
5432 to the LAN — without it, the Assembly PC cannot reach the database.
Note the OH PC's LAN IP (e.g. `192.168.1.50`); the Assembly PC needs it next.

Equivalent shortcuts via `make`: `make oh-build`, `make oh-up`, `make oh-migrate`.

### 4.2 Assembly PC (connects to OH PC's database — no local DB)

```bash
git clone <your-repo-url> blade-rocking   # or copy the folder over
cd blade-rocking
cp .env.assembly.example .env.assembly
```

Edit `.env.assembly`:

- `OH_SYNC_URL` — the OH PC's LAN IP, e.g. `http://192.168.1.50`
- `OH_SYNC_API_KEY` — must **exactly match** the value set in `.env.oh` on the OH PC
- `DATABASE_URL` — must point at the OH PC's Postgres, not a local container:
  `postgresql+asyncpg://blade_user:<OH_POSTGRES_PASSWORD>@192.168.1.50:5432/blade_rocking_oh`
  (same password you set for `POSTGRES_PASSWORD` in `.env.oh`)
- `REDIS_PASSWORD` — this one *is* local to the Assembly PC
- `SECRET_KEY` — generate independently (do **not** reuse the OH PC's key)

```bash
docker-compose -f docker-compose.assembly.yml --env-file .env.assembly up -d --build
docker-compose -f docker-compose.assembly.yml --env-file .env.assembly exec backend alembic upgrade head
```

Equivalent shortcuts via `make`: `make assembly-build`, `make assembly-up`, `make assembly-migrate`.

> Migrations only need to run once against the shared database — running
> `alembic upgrade head` from the Assembly PC is safe (Alembic no-ops if
> already up to date), but you generally only need to do it from OH.

### 4.3 Network checklist between the two PCs

- Both PCs on the same LAN/VLAN, static IPs recommended.
- OH PC firewall: allow inbound TCP `80` (and `443` if using HTTPS) and `5432` from the Assembly PC's IP.
- Assembly PC firewall: allow inbound TCP `80`/`443` for its own users.
- Confirm reachability before troubleshooting further: `curl http://<OH_PC_IP>/health` from the Assembly PC should return `{"status":"ok"}`.

---

## 5. Hardware Bridges (weighing scale / DTI gauge)

`scripts/weighing_bridge.py` and `scripts/dti_bridge.py` are **not** part of the
Docker stack — they run directly on the Windows PC physically wired (RS-232/USB)
to the scale or gauge, and push readings to the backend over HTTP.

On that Windows PC:

```bash
pip install pyserial requests

python scripts/weighing_bridge.py --server http://<server-IP>
python scripts/dti_bridge.py --port COM1 --station 1 --server http://<server-IP>
```

`<server-IP>` is the OH PC's LAN IP for OH-side rigs, or `localhost` if the
bridge runs on the same machine hosting the backend. Run `--help` on either
script for all options (COM port, baud rate, station number, measurement positions).

---

## 6. Verifying the deployment

```bash
docker-compose ps                              # all services "healthy"
curl http://localhost/health                   # {"status":"ok"}
docker-compose logs -f backend                  # watch for startup errors
```

Log in with a seeded account (change these passwords immediately after first login):

| Role | Email | Password |
|------|-------|----------|
| Super Admin | `admin@bladerocking.com` | `Admin@123` |
| OH Operator | `oh.operator@bladerocking.com` | `Test@123` |
| Assembly Operator | `assembly@bladerocking.com` | `Test@123` |
| QA Viewer | `qa.viewer@bladerocking.com` | `Test@123` |

---

## 7. Moving data to yet another machine later

To relocate the database itself (not just redeploy fresh):

```bash
# On the old machine — dump
docker-compose exec -T postgres pg_dump -U blade_user blade_rocking > backup.sql

# Copy backup.sql to the new machine, then, after `docker-compose up -d` there:
cat backup.sql | docker-compose exec -T postgres psql -U blade_user -d blade_rocking
```

Also copy the `uploads/` and `reports/` directories if attachments/reports need
to carry over — they're plain host-mounted folders, not part of the database.

---

## 8. Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `POSTGRES_PASSWORD must be set` on startup | `.env` / `.env.oh` / `.env.assembly` wasn't created or is missing that variable |
| Assembly PC backend can't reach the DB | OH PC didn't apply `docker-compose.oh-ports.yml`, or a firewall is blocking port 5432 |
| Backend container unhealthy | `docker-compose logs backend` — usually a bad `DATABASE_URL` or unapplied migration |
| Browser can't reach the app from another device | Machine's firewall is blocking port 80/443, or `CORS_ORIGINS` doesn't include the caller's origin |
| Bridge script can't open the COM port | Wrong `--port`, or another program (e.g. the scale's own utility) is holding the port open |
