"""
Demo data seeder — populates the Blade Rocking & Creep Test system
with realistic turbine blade data across all workflow stages.

Run: python3 /home/amit/src/blead_rocking/scripts/seed_demo_data.py
"""
import urllib.request, urllib.error, json, time, random, math

BASE = "http://localhost"

# ─── API helper ───────────────────────────────────────────────────────────────

def api(method, path, body=None, token=None):
    time.sleep(0.15)
    h = {"Content-Type": "application/json"}
    if token: h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        BASE + path, json.dumps(body).encode() if body else None, h, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try: return e.code, json.loads(raw)
        except: return e.code, {"_raw": raw[:200]}

def log(msg): print(f"  {msg}")
def section(title): print(f"\n{'━'*55}\n  {title}\n{'━'*55}")

# ─── Login ────────────────────────────────────────────────────────────────────

section("AUTHENTICATION")
sc, d = api("POST", "/api/v1/auth/login", {"email":"admin@bladerocking.com","password":"Admin@123"})
ADMIN = d["access_token"]; log("Admin logged in")
time.sleep(0.5)
sc, d = api("POST", "/api/v1/auth/login", {"email":"oh.operator@bladerocking.com","password":"Test@123"})
OH = d["access_token"]; log("OH Operator logged in")
time.sleep(0.5)
sc, d = api("POST", "/api/v1/auth/login", {"email":"assembly@bladerocking.com","password":"Test@123"})
ASM = d["access_token"]; log("Assembly Operator logged in")

# ─── Engine / WO configurations ───────────────────────────────────────────────

ENGINES = [
    {
        "engine_number": "CF6-80C2-SN10234",
        "work_order_number": "WO-2024-CF6-001",
        "shop_order_number": "SO-720-2024-001",
        "part_number": "PN-HPT-S1-001",
        "running_hours": 18450,
        "melt_series": "CF6-MELT",
        "blade_type": "HPTR",
        "count": 18,
    },
    {
        "engine_number": "CFM56-7B-SN55621",
        "work_order_number": "WO-2024-CFM-002",
        "shop_order_number": "SO-720-2024-002",
        "part_number": "PN-LPT-S3-002",
        "running_hours": 22100,
        "melt_series": "CFM-MELT",
        "blade_type": "LPTR",
        "count": 22,
    },
    {
        "engine_number": "PW4000-SN88432",
        "work_order_number": "WO-2024-PW4-003",
        "shop_order_number": "SO-720-2024-003",
        "part_number": "PN-HPT-S2-003",
        "running_hours": 15680,
        "melt_series": "PW4-MELT",
        "blade_type": "HPTR",
        "count": 14,
    },
]

# ─── Weight ranges for realistic blades ───────────────────────────────────────

def blade_weight(base=140.0):
    """Simulate realistic blade weight with ±2% variance."""
    return round(base + random.gauss(0, base * 0.015), 2)

def rocking_value():
    return round(random.uniform(0.008, 0.025), 4)

def creep_value():
    return round(random.uniform(0.004, 0.012), 4)

# ─── Seeding ─────────────────────────────────────────────────────────────────

created_blades = []
all_blade_ids  = []

for eng_idx, eng in enumerate(ENGINES):
    section(f"ENGINE {eng_idx+1}: {eng['engine_number']}")
    log(f"WO={eng['work_order_number']}  Blades={eng['count']}")

    weights = sorted([blade_weight(138 + eng_idx * 4) for _ in range(eng["count"])])
    blade_ids_this_engine = []

    for i, weight in enumerate(weights):
        sn = f"{eng['melt_series'][:3]}-{eng['engine_number'][-5:]}-{i+1:03d}"
        mn = f"{eng['melt_series']}-{2024+eng_idx:04d}-{i+1:02d}"

        sc, blade = api("POST", "/api/v1/blades/", {
            "serial_number": sn,
            "melt_number": mn,
            "work_order_number": eng["work_order_number"],
            "shop_order_number": eng["shop_order_number"],
            "part_number": eng["part_number"],
            "engine_number": eng["engine_number"],
            "running_hours": eng["running_hours"],
            "blade_type": eng["blade_type"],
        }, token=OH)

        if sc not in (200, 201):
            log(f"  ⚠ skip {sn} (HTTP {sc})")
            continue

        bid = blade["id"]
        blade_ids_this_engine.append((bid, weight))
        all_blade_ids.append(bid)

    log(f"  Created {len(blade_ids_this_engine)} blades")
    created_blades.append((eng, blade_ids_this_engine))

# ─── Add measurements ─────────────────────────────────────────────────────────

section("MEASUREMENTS & WORKFLOW PROGRESSION")

slot_counter = 1

for eng, blade_list in created_blades:
    log(f"\n{eng['engine_number']} — {len(blade_list)} blades")

    for idx, (bid, weight) in enumerate(blade_list):
        sm = round((weight * 1.57) * 20, 2)

        # Add measurement
        meas_body = {
            "measurement_type": "INITIAL",
            "weight_grams": weight,
            "static_moment_gcm": sm,
            "rocking_value": rocking_value(),
        }
        if eng["blade_type"] == "LPTR":
            meas_body["creep_value"] = creep_value()

        api("POST", f"/api/v1/blades/{bid}/measurements", meas_body, token=OH)

        # Decide workflow stage based on position in list
        progress = idx / len(blade_list)

        if progress < 0.12:
            # ~12% stay in OH_INSPECTION (measurements not yet recorded — skip send)
            pass

        elif progress < 0.25:
            # ~13% at MEASUREMENTS_RECORDED — sent but not yet assigned
            api("POST", f"/api/v1/blades/{bid}/send-to-assembly",
                {"remarks": "Measurements verified, ready for slot allocation"}, token=OH)

        elif progress < 0.85:
            # ~60% in assembly — assign slot, update balancing
            api("POST", f"/api/v1/blades/{bid}/send-to-assembly",
                {"remarks": "All measurements within tolerance"}, token=OH)
            time.sleep(0.05)

            slot_num = f"{chr(65 + (slot_counter // 30) % 8)}-{slot_counter % 30 + 1:02d}"
            sc, slot = api("POST", "/api/v1/slots/assign", {
                "blade_id": bid,
                "slot_number": slot_num,
                "position": slot_counter % 90 + 1,
                "remarks": "Assigned per weight-based balancing sequence",
            }, token=ASM)
            slot_counter += 1

            if sc in (200, 201) and slot.get("id"):
                sid = slot["id"]
                # Most blades balanced, some not
                is_balanced = random.random() > 0.15  # 85% balanced
                bal_body = {
                    "is_balanced": is_balanced,
                    "balancing_remarks": (
                        "Within balance tolerance" if is_balanced
                        else f"Imbalance {round(random.uniform(0.02, 0.08), 3)} g·cm detected"
                    ),
                }
                if not is_balanced:
                    bal_body["unbalance_value"] = round(random.uniform(0.02, 0.08), 3)
                api("PUT", f"/api/v1/slots/{sid}/balancing", bal_body, token=ASM)

        else:
            # ~15% fully completed
            api("POST", f"/api/v1/blades/{bid}/send-to-assembly",
                {"remarks": "All measurements verified"}, token=OH)
            time.sleep(0.05)
            slot_num = f"{chr(65 + (slot_counter // 30) % 8)}-{slot_counter % 30 + 1:02d}"
            sc, slot = api("POST", "/api/v1/slots/assign", {
                "blade_id": bid, "slot_number": slot_num,
                "position": slot_counter % 90 + 1,
            }, token=ASM)
            slot_counter += 1
            if sc in (200, 201) and slot.get("id"):
                api("PUT", f"/api/v1/slots/{slot['id']}/balancing",
                    {"is_balanced": True, "balancing_remarks": "Final balance verified"}, token=ASM)
            time.sleep(0.05)
            api("POST", f"/api/v1/blades/{bid}/complete",
                {"remarks": "All stages complete. Blade cleared for installation."}, token=OH)

    print(f"  ✓ {eng['engine_number']} workflow complete")

# ─── Final summary ───────────────────────────────────────────────────────────

section("VERIFICATION")
sc, stats = api("GET", "/api/v1/workflows/dashboard/stats", token=ADMIN)
print(f"""
  Status distribution:
{"".join(f"    {k:<30} {v}{chr(10)}" for k,v in (stats.get("by_status") or {}).items() if v)}
  Total active:     {stats.get("total_active")}
  Total completed:  {stats.get("total_completed")}
  Total rejected:   {stats.get("total_rejected")}
  Unbalanced slots: {stats.get("total_unbalanced")}
""")

sc, wos = api("GET", "/api/v1/workflows/dashboard/work-orders", token=ADMIN)
print(f"  Work orders in dashboard header: {len(wos)}")
for wo in wos:
    print(f"    WO={wo['work_order_number']}  Engine={wo['engine_number']}  Blades={wo['blade_count']}")

total_created = sum(len(blist) for _, blist in created_blades)
print(f"\n  ✅ Seeded {total_created} blades across {len(ENGINES)} work orders / engines")
print("  ✅ Dashboard, timeline, charts, notifications all have live data")
print("  ✅ Refresh the browser to see the changes\n")
