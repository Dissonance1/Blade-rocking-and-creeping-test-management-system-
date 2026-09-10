# Deployment Guide — Running This System on a New PC or Device

This guide covers taking the Blade Rocking & Creep Test Management System from
this repository and standing it up on a machine that has never run it before —
whether that's a single demo laptop or the real factory-floor deployment.

Everything runs in Docker, so the target machine does **not** need Python,
Node.js, PostgreSQL, or Redis installed — only Docker itself. The one exception
is the hardware bridge scripts (weighing scale / DTI gauge / OCR camera), which
run directly on Windows and only exist on the OH PC — see
[Hardware Bridges](#hardware-bridges-weighing-scale--dti-gauge).

> This guide only uses placeholder secrets. The actual `SECRET_KEY` / DB /
> Redis values currently deployed on this machine's `.env` / `.env.oh` are
> recorded in `CREDENTIALS.local.md` at the repo root — that file is
> gitignored and must never be committed.

---

## 1. Which setup do you need?

| Setup | When to use | Compose file |
|-------|-------------|------------------|
| **Single machine** | Demo, dev laptop, or a single-PC deployment with everything (DB included) on one box | `docker-compose.yml` |
| **Plant (OH station) production** | Real factory floor — one PC (701 Hanger) runs the whole stack (DB included) and acts as the server; every other PC/device on the plant LAN just opens a browser to it, nothing installed | `docker-compose.oh.yml` |

If you're just trying the system out, use **Section 3 (Single machine)**.
If you're replicating the real plant deployment, use **Section 4 (Plant/OH station)**.

> **Note on Assembly:** an earlier version of this deployment ran a *second*
> full stack on a separate Assembly PC (`docker-compose.assembly.yml`), with
> its own backend pointed at the OH PC's Postgres over LAN. That's been
> removed — Assembly has no local hardware (no OCR camera, scale, or DTI
> gauge) that would need a local backend to bridge into, so there was nothing
> a second stack bought beyond needless duplication. Assembly staff now just
> browse to the OH PC directly (see Section 4.2) — role-based access
> (`ASSEMBLY_OPERATOR` vs `OH_OPERATOR`) is what actually restricts what they
> can do, not which PC they're sitting at.

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

## 4. Plant production setup (OH PC as the shared server)

### 4.1 OH PC (runs the whole stack)

```bash
git clone <your-repo-url> blade-rocking   # or copy the folder over
cd blade-rocking
cp .env.oh.example .env.oh
```

Edit `.env.oh`:

- `POSTGRES_PASSWORD` — pick a strong password
- `REDIS_PASSWORD`
- `SECRET_KEY` — generate independently (`python3 -c "import secrets; print(secrets.token_hex(32))"`)
- `CORS_ORIGINS` — not required for normal browser use (the frontend calls the
  API via a relative path, so any browser reaching this PC through nginx is
  same-origin regardless of which address it used) but kept as a defensive
  allowlist for anything that calls the API directly (Swagger UI at `/docs`,
  external tools). Add this PC's static LAN IP if you want it covered, e.g.
  `["http://192.168.1.50","https://192.168.1.50"]`.

```bash
docker-compose -f docker-compose.oh.yml build
docker-compose -f docker-compose.oh.yml up -d
docker-compose -f docker-compose.oh.yml exec oh_backend alembic upgrade head
docker-compose -f docker-compose.oh.yml exec oh_backend python ../scripts/seed_data.py   # first time only
```

Note this PC's static LAN IP (e.g. `192.168.1.50`) — that's the address every
other PC/device on the plant LAN will use to reach the app.

Equivalent shortcuts via `make`: `make oh-build`, `make oh-up`, `make oh-migrate`.

### 4.2 Every other PC (Assembly included) — nothing to install

There is no separate Assembly stack, no local database, no `.env` file to
create. Anyone on the plant LAN — Assembly staff included — just opens a
browser and goes to `http://<OH_PC_IP>/`, logs in with their own account, and
sees only what their role (`ASSEMBLY_OPERATOR`, `OH_OPERATOR`, etc. — see
[CLAUDE.md](../CLAUDE.md#auth--roles)) permits. A `SUPER_ADMIN` creates those
accounts from the User Management page; nobody needs shell/Docker access on
their own machine to use the app.

### 4.3 Network checklist

- OH PC has a **static LAN IP** (DHCP-assigned addresses can silently change
  on a router reboot and break everyone's bookmark — use a static IP or a
  DHCP reservation).
- OH PC firewall: allow inbound TCP `80` (and `443` if using HTTPS) from the
  rest of the LAN. Postgres's port (`5432`) does **not** need to be exposed to
  the LAN at all — nothing outside this PC talks to the database directly
  anymore, only the app's own backend container does, over the internal
  Docker network.
- Confirm reachability from another device before troubleshooting further:
  `curl http://<OH_PC_IP>/health` should return `{"status":"ok"}`.

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
| `POSTGRES_PASSWORD must be set` on startup | `.env` / `.env.oh` wasn't created or is missing that variable |
| Backend container unhealthy | `docker-compose logs backend` — usually a bad `DATABASE_URL` or unapplied migration |
| Browser can't reach the app from another device | Most likely a physical/network-layer issue, not the app: check the OH PC's firewall is allowing port 80/443, that both devices are actually on the same LAN, and that the OH PC's network adapter for that LAN shows as connected (`Get-NetAdapter` on Windows) rather than assuming a DHCP/Wi-Fi address is the one to use — a device on a different network segment simply can't route to it. `CORS_ORIGINS` is very unlikely to be the cause (the frontend calls the API same-origin) but is a defensive allowlist worth checking last. |
| Bridge script can't open the COM port | Wrong `--port`, or another program (e.g. the scale's own utility) is holding the port open |
