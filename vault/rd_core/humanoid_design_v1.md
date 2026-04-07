# THIRAMAI R&D — Scrap-Based Humanoid Chassis v1

**Parent strategy:** [`humanoid_robotics_roadmap.md`](./humanoid_robotics_roadmap.md) (Empire Vision · Q1–Q2 *Materials lab & CAD library*).

**Design intent:** Use **factory HDPE/PVC waste** (offcuts, start-up pips, off-spec colour batches — *not* potable-certified stock) as feedstock for **shred → granulate → FDM filament** (or direct pellet extrusion) to print **joints, guards, and cable ducts** for a **lightweight torso / hip module** (~350–450 mm shoulder width class).

---

## Material strategy

| Source stream | Part families | Notes |
|---------------|---------------|--------|
| **HDPE PE100/PE80 scrap** | Torso corner brackets, hip clevis blocks, battery tray ribs | Prefer **3–4 perimeter shells**, **≥35% infill** triangular; avoid long cantilevers >45 mm without ribs. |
| **Rigid PVC scrap** | Wrist / forearm shrouds, sensor cowls, end-stop bumpers | Higher stiffness; watch **print temperature band** vs extruder limits on recycled PVC (validate on coupon first). |
| **Line offcuts (mixed)** | Prototype iteration only until batch colour/MFI is segregated | Tag spool ID ↔ extrusion batch in `vault/` notes. |

---

## CAD library — Prototype 01 (metric, ISO general tolerances unless noted)

### A. Revolute bushing pair (scrap HDPE, FDM)

- **Bushing OD:** 32.0 mm (free fit on commercial 8 mm shoulder bolt / threaded standoff).
- **ID (clearance for M8):** 8.5 mm through-hole, length **12.0 mm** metal sleeve zone; plastic bearing section **10.0 mm** long × **8.3 mm** ID (slip fit after ream).
- **Flange OD:** 42.0 mm × **3.0 mm** thick — **4×** M3 countersunk holes on **34 mm** PCD, 90° apart.
- **Print orientation:** Flange on bed; **layer lines** around hoop stress (axis vertical). **Wall:** 4 shells @ **0.4 mm** nozzle → **1.6 mm** effective wall; **solid layers** top/bottom **8**.

### B. Clevis block (hip / knee link, HDPE)

- **Body:** 48 × 24 × 36 mm (L × W × H).
- **Pin bore:** **8.0 mm** reamed (plastic pin) or **6 mm** steel dowel + **6.1 mm** bore.
- **Fork gap:** **8.2 mm** (for **6 mm** link plate).
- **Fillet:** **R3** internal min on printed version; add **1.5 mm** rib **24 mm** tall on compression side.

### C. Torso guard shell (PVC or HDPE, 2× mirrored halves)

- **Developed panel (single half):** approx. **220 × 180 mm** planar unfold; **2.5 mm** nominal wall; **12 mm** snap undercut depth (cantilever snap — **beam length 5 mm**, **root R1**).
- **Vent pattern:** **6 mm** holes, **15 mm** grid (manufacturing + thermal).

### D. Cable duct clip (HDPE, quick print)

- **Channel ID:** **12 × 8 mm** (for bundled CAN + 24 V).
- **Strap thickness:** **2.0 mm**; **50 mm** overall length; **M4** self-tapping boss **OD 6.8 mm**.

---

## Assembly / BOM hints (non-binding)

- Commercial **6061 or steel** carries primary **bending moment**; printed parts are **secondary structure** and **guards** until PE100 laminates are qualified.
- Target **>60% polymer mass** on shell module (roadmap) excludes motors/battery cells.

---

## Next physical step (for brain / CEO echo)

1. **Run** `python factory/design_engine.py` and archive the **Material Suitability Report** for PE100 in the vault or daily log.
2. **CAD:** Export **Revolute bushing pair (§A)** as STEP/STL; slice at **0.2 mm** layers, **220 °C** nozzle start (adjust ±5 °C for recycled HDPE MFI), **bed 95–100 °C** (PEI sheet).
3. **Print one clevis (§B)** and one **duct clip (§D)** on the same spool batch; **measure** pin bore and fork gap with calipers; update this file if shrinkage ≠ **0.4–0.8%** in XY.

---

## Traceability

- Link financial **Robotics Fund** (dashboard Cash Flow Radar) to purchase of **dryer / shredder wear parts** or **filament qualification spools** — keep ledger separate from potable resin CAPEX.

*Revision: v1 — Empire Phase 8. Align detailed CAPEX with DPR and `business_current.txt`.*
