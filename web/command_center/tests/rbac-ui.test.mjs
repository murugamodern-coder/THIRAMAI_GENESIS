import test from "node:test";
import assert from "node:assert/strict";

import { visibleNavForRole } from "../src/lib/navigationVisibility.js";
import { ROLES, defaultRouteForRole } from "../src/lib/rbac.js";

test("owner sees all primary sections", () => {
  const items = visibleNavForRole(ROLES.OWNER);
  const keys = items.map((x) => x.key);
  assert.deepEqual(keys, ["brain", "tasks", "business", "money", "research", "build"]);
});

test("staff sees limited business nav only", () => {
  const items = visibleNavForRole(ROLES.STAFF);
  const keys = items.map((x) => x.key);
  assert.deepEqual(keys, ["business"]);
  assert.equal(defaultRouteForRole(ROLES.STAFF), "/dashboard/inventory");
});

test("family sees personal-only task entry", () => {
  const items = visibleNavForRole(ROLES.FAMILY);
  assert.equal(items.length, 1);
  assert.equal(items[0].key, "tasks");
  assert.equal(items[0].to, "/personal");
  assert.equal(defaultRouteForRole(ROLES.FAMILY), "/personal");
});
