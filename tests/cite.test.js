// node --test tests/  — citation parsing/resolution in web/app.js (pure helpers, no DOM).
const test = require("node:test");
const assert = require("node:assert/strict");
const { prepare, resolveCite } = require("../web/app.js");

// Search-index shape produced by bns/site.py: s = [num, heading, chapter], n = [id, sectionIndex, cite, text, depth].
const idx = prepare({
  s: [["2", "Definitions.", "I"], ["64", "Punishment for rape.", "V"], ["101", "Murder.", "VI"], ["8", "Amount of fine…", "II"]],
  n: [
    ["2(8)", 0, "Section 2(8)", "“document” means …", 1],
    ["2(8)-expl-1", 0, "Explanation 1 to Section 2(8)", "It is immaterial …", 2],
    ["2(8)-expl-1-illus-a", 0, "Illustration (a) to Explanation 1 to Section 2(8)", "A writing …", 3],
    ["2(28)", 0, "Section 2(28)", "“public servant” …", 1],
    ["2(28)(k)", 0, "Section 2(28)(k)", "every person—", 2],
    ["2(28)(k)(ii)", 0, "Section 2(28)(k)(ii)", "in the service …", 3],
    ["64(2)", 1, "Section 64(2)", "Whoever,—", 1],
    ["64(2)(f)", 1, "Section 64(2)(f)", "being a relative …", 2],
    ["101-exc-4", 2, "Exception 4 to Section 101", "Culpable homicide …", 1],
    ["101-exc-4-expl", 2, "Explanation to Exception 4 to Section 101", "It is immaterial …", 2],
    ["8(5)", 3, "Section 8(5)", "If the offence …", 1],
    ["8(5)-proviso-1", 3, "First proviso to Section 8(5)", "Provided …", 2],
    ["8(5)-proviso-2", 3, "Second proviso to Section 8(5)", "Provided further …", 2],
  ],
});

const to = (q) => {
  const r = resolveCite(idx, q);
  return r && [r.id, r.exact];
};

test("compact and prefixed section citations", () => {
  assert.deepEqual(to("64(2)(f)"), ["64(2)(f)", true]);
  assert.deepEqual(to("s. 64(2)(F)"), ["64(2)(f)", true]);
  assert.deepEqual(to("Section 2(28)(k)(ii) of BNS"), ["2(28)(k)(ii)", true]);
  assert.deepEqual(to("BNS 101"), ["101", true]);
  assert.deepEqual(to("§ 64"), ["64", true]);
});

test("missing sub-provision falls back to nearest ancestor, not exact", () => {
  assert.deepEqual(to("2(28)(k)(ix)"), ["2(28)(k)", false]);
  assert.deepEqual(to("64(9)"), ["64", false]);
  assert.equal(to("999"), null);
  assert.equal(to("murder"), null);
});

test("Explanation / Exception / proviso / Illustration citations", () => {
  assert.deepEqual(to("Explanation to Exception 4 to section 101"), ["101-exc-4-expl", true]);
  assert.deepEqual(to("Exception 4 of section 101 BNS"), ["101-exc-4", true]);
  assert.deepEqual(to("second proviso to s. 8(5)"), ["8(5)-proviso-2", true]);
  assert.deepEqual(to("proviso to section 8(5)"), ["8(5)-proviso-1", true]);
  assert.deepEqual(to("Explanation 1 to section 2(8)"), ["2(8)-expl-1", true]);
  // Illustration filed under an Explanation is still found from the provision.
  assert.deepEqual(to("Illustration (a) to section 2(8)"), ["2(8)-expl-1-illus-a", true]);
  // Unknown qualifier target falls back to the provision.
  assert.deepEqual(to("Explanation 3 to section 64(2)"), ["64(2)", false]);
});

test("raw fragment ids resolve directly", () => {
  assert.deepEqual(to("101-exc-4-expl"), ["101-exc-4-expl", true]);
});
