// Logic check for lib/georef.ts in plain Node (Node 22.18+ or 24 runs the .ts file directly by
// stripping its types). Run from mobile/: `npm run check:georef`.
//
// Checks: round trips, a known rotation, the mirror (handedness) check, exact and mirrored solves,
// the GPS start accuracy rule, and a Monte Carlo of how GPS noise turns into rotation error for the
// real spots in demo/rabinowitz/building.json (read only; skipped if the file is not there).

import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  judgeStartFix,
  latLngToPlan,
  MAX_SNAP_DISTANCE_M,
  MAX_START_ACCURACY_M,
  normalizeDeg,
  planToLatLng,
  solveCalibration,
  toEastNorth,
} from '../lib/georef.ts';

let failures = 0;
function check(name, ok, detail = '') {
  if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? `  (${detail})` : ''}`);
}

// Seeded random numbers, so the report is the same on every run.
let seed = 20261114;
function rand() {
  seed = (seed * 1664525 + 1013904223) % 4294967296;
  return seed / 4294967296;
}
function gauss() {
  const u = Math.max(rand(), 1e-12);
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rand());
}

const ORIGIN = { lat: 40.34908933610458, lng: -74.65546592669608 }; // the demo building's Matterport lat/lng
const T = (rotationDeg, tx = 3, tz = -2) => ({ originLat: ORIGIN.lat, originLng: ORIGIN.lng, rotationDeg, tx, tz });
const moveEN = (e, n) => ({
  lat: ORIGIN.lat + n / (6_371_008.8 * (Math.PI / 180)),
  lng: ORIGIN.lng + e / (6_371_008.8 * (Math.PI / 180) * Math.cos((ORIGIN.lat * Math.PI) / 180)),
});

// 1. Round trips.
{
  let worst = 0;
  for (let i = 0; i < 2000; i += 1) {
    const t = T(rand() * 360 - 180, rand() * 40 - 20, rand() * 40 - 20);
    const p = { x: rand() * 60 - 30, z: rand() * 60 - 30 };
    const back = latLngToPlan(t, planToLatLng(t, p));
    worst = Math.max(worst, Math.hypot(back.x - p.x, back.z - p.z));
    const ll = moveEN(rand() * 60 - 30, rand() * 60 - 30);
    const ll2 = planToLatLng(t, latLngToPlan(t, ll));
    const en = toEastNorth(ll, ll2);
    worst = Math.max(worst, Math.hypot(en.e, en.n));
  }
  check('round trips plan -> lat/lng -> plan and back', worst < 1e-6, `worst ${worst.toExponential(2)} m`);
}

// 2. Known rotations: with rotation 0, east is +x and north is -z; with 90, east is -z and north is -x.
{
  const close = (a, b) => Math.abs(a.x - b.x) < 1e-6 && Math.abs(a.z - b.z) < 1e-6;
  check('rotation 0: 10 m east -> x + 10', close(latLngToPlan(T(0), moveEN(10, 0)), { x: 13, z: -2 }));
  check('rotation 0: 10 m north -> z - 10', close(latLngToPlan(T(0), moveEN(0, 10)), { x: 3, z: -12 }));
  check('rotation 90: 10 m east -> z - 10', close(latLngToPlan(T(90), moveEN(10, 0)), { x: 3, z: -12 }));
  check('rotation 90: 10 m north -> x - 10', close(latLngToPlan(T(90), moveEN(0, 10)), { x: -7, z: -2 }));
  check('normalizeDeg', normalizeDeg(190) === -170 && normalizeDeg(-180) === 180 && normalizeDeg(540) === 180);
}

// 3. Mirror check: FloorPlan draws x right and z down, so screen "up" is -z. On a top view that is not
// mirrored, turning from east to north is counterclockwise on screen (positive cross product).
{
  let allCcw = true;
  for (let deg = -180; deg < 180; deg += 7.5) {
    const t = T(deg);
    const o = latLngToPlan(t, moveEN(0, 0));
    const e = latLngToPlan(t, moveEN(1, 0));
    const n = latLngToPlan(t, moveEN(0, 1));
    const se = { x: e.x - o.x, y: -(e.z - o.z) };
    const sn = { x: n.x - o.x, y: -(n.z - o.z) };
    if (se.x * sn.y - se.y * sn.x <= 0) allCcw = false;
  }
  check('drawn plan is never mirrored (east to north turns counterclockwise on screen at every rotation)', allCcw);
}

// Real spots from the demo building.
const here = dirname(fileURLToPath(import.meta.url));
const buildingPath = join(here, '..', '..', 'demo', 'rabinowitz', 'building.json');
const building = existsSync(buildingPath) ? JSON.parse(readFileSync(buildingPath, 'utf8')) : null;
const CAM = '1k478kza39tbfu1uhbttg5ybb';
const AED = '0f2a2fyf5iibscursb5gkyu9a';
const nodes = building ? building.twin_nodes : [];
const node = (id) => nodes.find((n) => n.sweep_id === id);
const spotsAll = nodes.filter((n) => n.label).map((n) => ({ id: n.sweep_id, label: n.label, plan: { x: n.x, z: n.z } }));
const floor2 = nodes.filter((n) => n.floor === 2).map((n) => ({ id: n.sweep_id, x: n.x, z: n.z }));

// 4. Exact solves recover the transform; a mirrored world is caught by the mirror diagnostic.
{
  const spots =
    spotsAll.length >= 3
      ? spotsAll
      : [
          { id: 'a', plan: { x: 0, z: 0 } },
          { id: 'b', plan: { x: -11, z: 0 } },
          { id: 'c', plan: { x: -8, z: 13 } },
        ];
  const truth = T(37.5, 1.2, -4.4);
  const exact = solveCalibration(spots.map((s) => ({ id: s.id, fix: planToLatLng(truth, s.plan), plan: s.plan })));
  // Tolerance 0.1 mm: the solve uses the mean of the fixes as its origin, and the flat-earth
  // approximation differs between two origins a few meters apart by parts per million.
  const TOL = 1e-4;
  const probe = { x: 9, z: -3 };
  const a = latLngToPlan(truth, planToLatLng(truth, probe));
  const b = latLngToPlan(exact.transform, planToLatLng(truth, probe));
  check(
    `exact solve from ${spots.length} spots recovers the rotation and the mapping`,
    Math.abs(normalizeDeg(exact.transform.rotationDeg - 37.5)) < 1e-3 && Math.hypot(a.x - b.x, a.z - b.z) < TOL && exact.rmsM < TOL,
    `rotation ${exact.transform.rotationDeg.toFixed(6)}, rms ${exact.rmsM.toExponential(2)} m, mirrored rms ${exact.mirroredRmsM?.toFixed(2)} m`,
  );
  // Fixes from a mirrored world (z flipped): the real fit is bad and the mirrored fit is exact.
  const mirroredFixes = spots.map((s) => ({ id: s.id, fix: planToLatLng(truth, { x: s.plan.x, z: -s.plan.z }), plan: s.plan }));
  const m = solveCalibration(mirroredFixes);
  check(
    'mirror diagnostic flags fixes that only fit a mirrored plan',
    m.mirroredRmsM !== null && m.mirroredRmsM < TOL && m.rmsM > 1,
    `fit rms ${m.rmsM.toFixed(2)} m, mirrored rms ${m.mirroredRmsM?.toExponential(2)} m`,
  );
  check('fewer than two spots: no solve', solveCalibration(spots.slice(0, 1).map((s) => ({ id: s.id, fix: ORIGIN, plan: s.plan }))) === null);
  check(
    'two fixes in the same place: no solve',
    solveCalibration([
      { id: 'a', fix: ORIGIN, plan: { x: 0, z: 0 } },
      { id: 'b', fix: ORIGIN, plan: { x: 5, z: 0 } },
    ]) === null,
  );
}

// 5. GPS start accuracy rule.
{
  const t = T(20, 0, 0);
  const plan = floor2.length ? floor2 : [{ id: 'a', x: 0, z: 0 }, { id: 'b', x: 5, z: 0 }];
  const at = (p, accuracyM) => ({ ...planToLatLng(t, p), accuracyM });
  const all = () => true;
  const target = plan[0];
  const near = judgeStartFix(t, at({ x: target.x + 0.4, z: target.z - 0.3 }, 6), plan, all);
  check('good fix snaps to the nearest sweep', near.ok && near.sweepId === target.id && Math.round(near.accuracyM) === 6);
  check('no accuracy reported: not used', judgeStartFix(t, at(target, null), plan, all).reason === 'no_accuracy');
  check(`accuracy worse than ${MAX_START_ACCURACY_M} m: not used`, judgeStartFix(t, at(target, MAX_START_ACCURACY_M + 0.5), plan, all).reason === 'poor_accuracy');
  check(`accuracy exactly ${MAX_START_ACCURACY_M} m: used`, judgeStartFix(t, at(target, MAX_START_ACCURACY_M), plan, all).ok === true);
  const xs = plan.map((p) => p.x);
  const far = { x: Math.max(...xs) + MAX_SNAP_DISTANCE_M + 5, z: plan[0].z };
  check(`more than ${MAX_SNAP_DISTANCE_M} m from every sweep: off the map`, judgeStartFix(t, at(far, 5), plan, all).reason === 'off_map');
  const onlyOther = judgeStartFix(t, at(target, 5), plan, (id) => id !== target.id);
  check('snaps only to sweeps that can reach the target', onlyOther.ok && onlyOther.sweepId !== target.id);
}

// 6. Noisy calibration: how rotation error grows with GPS noise over the real spot distances.
if (building) {
  const truth = T(0, 0, 0);
  const camN = node(CAM);
  const aedN = node(AED);
  const farthestFrom = (pts) => {
    const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length;
    const cz = pts.reduce((s, p) => s + p.z, 0) / pts.length;
    return Math.max(...floor2.map((n) => Math.hypot(n.x - cx, n.z - cz)));
  };
  const scenarios = [
    { name: 'patient spot + AED spot', spots: [camN, aedN] },
    { name: 'patient spot + "corridor wing" (longest pair from the patient)', spots: [camN, node('w5kacr4ci0d92c5wkzrfs4erd')] },
    { name: 'all 4 labeled spots', spots: spotsAll.map((s) => node(s.id)) },
  ];
  console.log('');
  console.log('Noisy calibration (Monte Carlo, 4000 runs per row). Each fix gets independent Gaussian noise of');
  console.log('sigma meters on east and on north. Position error is the rotation error alone, measured at the floor 2');
  console.log('sweep farthest from the spots\' centroid; translation error from the noise comes on top of it.');
  for (const sc of scenarios) {
    const pts = sc.spots.map((n) => ({ id: n.sweep_id, plan: { x: n.x, z: n.z } }));
    const span =
      pts.length === 2 ? Math.hypot(pts[0].plan.x - pts[1].plan.x, pts[0].plan.z - pts[1].plan.z) : null;
    const reach = farthestFrom(pts.map((p) => p.plan));
    console.log('');
    console.log(`${sc.name}${span !== null ? `, ${span.toFixed(2)} m apart` : ''}; farthest floor 2 sweep ${reach.toFixed(1)} m from their centroid`);
    console.log('  sigma   rotation error median / 90th pct      position error from rotation, median / 90th pct');
    for (const sigma of [1, 2, 3, 5, 8, 10]) {
      const errs = [];
      for (let i = 0; i < 4000; i += 1) {
        const noisy = pts.map((p) => {
          const ll = planToLatLng(truth, p.plan);
          const en = toEastNorth(ORIGIN, ll);
          return { id: p.id, plan: p.plan, fix: moveEN(en.e + sigma * gauss(), en.n + sigma * gauss()) };
        });
        const solved = solveCalibration(noisy);
        if (solved) errs.push(Math.abs(normalizeDeg(solved.transform.rotationDeg)));
      }
      errs.sort((a, b) => a - b);
      const q = (f) => errs[Math.min(errs.length - 1, Math.floor(f * errs.length))];
      const pos = (deg) => 2 * reach * Math.sin(((deg * Math.PI) / 180) / 2);
      console.log(
        `  ${String(sigma).padStart(3)} m    ${q(0.5).toFixed(1).padStart(5)} / ${q(0.9).toFixed(1).padStart(5)} degrees` +
          `                    ${pos(q(0.5)).toFixed(1).padStart(5)} / ${pos(q(0.9)).toFixed(1).padStart(5)} m`,
      );
    }
  }
} else {
  console.log('demo/rabinowitz/building.json not found: skipped the real-data checks.');
}

console.log('');
console.log(failures === 0 ? 'All checks passed.' : `${failures} check(s) FAILED.`);
process.exit(failures === 0 ? 0 : 1);
