// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

function contractBytes(version) {
  return readFileSync(
    new URL(`../../contracts/trio-composition-v${version}.json`, import.meta.url),
  );
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

const historicalV4Bytes = contractBytes(4);
assert.equal(
  sha256(historicalV4Bytes),
  "5a1a0de38cdf914f4e722b66f74e5f989862e2fae0fa628e6bdcae68ce57a02c",
  "historical trio composition v4 bytes changed",
);

const activeV5Bytes = contractBytes(5);
assert.equal(
  sha256(activeV5Bytes),
  "fcf423a217d75dc76a8b3fba89d4e0045d6e852dc507fea8d8d81a6a8e7d4744",
  "active trio composition v5 bytes changed",
);
const active = JSON.parse(activeV5Bytes.toString("utf8"));
assert.equal(active.contractId, "tinysa-trio-composition");
assert.equal(active.contractVersion, 5);
assert.equal(active.$id, "https://tinysa.local/contracts/trio-composition-v5.json");
assert.equal(active.parties.signalLab.standaloneApiVersion, 2);
assert.equal(active.parties.signalLab.measurementBridgeContractVersion, 2);
assert.equal(active.parties.signalLab.closedProfileCount, 42);
assert.equal(active.parties.signalLab.fixedDigitalProfileCount, 31);
assert.equal(active.parties.signalLab.rateFlexibleProfileCount, 11);

const measurementEdge = active.edges.find(
  ({ producer, consumer }) =>
    producer === "signalLab" && consumer === "atomizer",
);
assert.ok(measurementEdge, "active SignalLab-to-Atomizer edge is missing");
assert.equal(measurementEdge.status, "active");
assert.equal(measurementEdge.transport, "in-process-typescript-direct-import");
assert.equal(measurementEdge.serialization, "none");
assert.equal(measurementEdge.processBoundary, "none");
assert.equal(
  measurementEdge.contract,
  "contracts/signal-lab-measurement-bridge-v2.json",
);
assert.ok(
  measurementEdge.guarantees.some((guarantee) =>
    guarantee.includes("I/Q is a digital sample interface"),
  ),
  "active edge must keep digital I/Q distinct from antenna qualification",
);

const firmwareEdge = active.edges.find(
  ({ producer, consumer }) =>
    producer === "firmware" && consumer === "atomizer",
);
assert.equal(
  firmwareEdge?.transport,
  "renode-monitor-bridge-through-tinysa-zs407-driver",
  "the independent Firmware-twin transport changed",
);

const reservedStimulusEdge = active.edges.find(
  ({ producer, consumer }) =>
    producer === "signalLab" && consumer === "firmware",
);
assert.equal(reservedStimulusEdge?.status, "reserved-not-connected");
assert.match(active.compatibility.verification, /byte-identical v5 copies/);
assert.match(
  active.compatibility.verification,
  /unchanged historical v1 and v4 contract hashes/,
);

console.log(
  `Trio composition v5 semantics: passed (${sha256(activeV5Bytes)})`,
);
