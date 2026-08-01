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

const historicalV5Bytes = contractBytes(5);
assert.equal(
  sha256(historicalV5Bytes),
  "fcf423a217d75dc76a8b3fba89d4e0045d6e852dc507fea8d8d81a6a8e7d4744",
  "historical trio composition v5 bytes changed",
);
const historicalV6Bytes = contractBytes(6);
assert.equal(
  sha256(historicalV6Bytes),
  "37421c8bb2a7d3c93804f00da0e4cbb2bd32dab0a4a3b1e915ac27f6e621d596",
  "historical trio composition v6 bytes changed",
);
const activeV7Bytes = contractBytes(7);
const active = JSON.parse(activeV7Bytes.toString("utf8"));
assert.equal(active.contractId, "tinysa-trio-composition");
assert.equal(active.contractVersion, 7);
assert.equal(active.$id, "https://tinysa.local/contracts/trio-composition-v7.json");
assert.equal(active.parties.signalLab.standaloneApiVersion, 2);
assert.equal(active.parties.signalLab.measurementBridgeContractVersion, 3);
assert.equal(active.parties.signalLab.closedProfileCount, 44);
assert.equal(active.parties.signalLab.fixedDigitalProfileCount, 31);
assert.equal(active.parties.signalLab.rateFlexibleProfileCount, 11);
assert.equal(active.parties.signalLab.unboundedCompositionProfileCount, 2);
assert.ok(
  active.parties.atomizer.registeredDrivers.some(
    ({ driverId }) => driverId === "neptune-p210",
  ),
  "active composition must retain the separately owned Neptune driver",
);

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
  "contracts/signal-lab-measurement-bridge-v3.json",
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

const neptuneEdge = active.edges.find(
  ({ producer, consumer }) =>
    producer === "neptune-p210" && consumer === "atomizer",
);
assert.equal(neptuneEdge?.status, "active");
assert.equal(neptuneEdge?.transport, "libiio-network-through-neptune-p210-driver");
assert.ok(
  neptuneEdge?.guarantees.some((guarantee) =>
    guarantee.includes("capture starts are paced"),
  ),
  "active Neptune edge must retain hardware capture protection",
);

const reservedStimulusEdge = active.edges.find(
  ({ producer, consumer }) =>
    producer === "signalLab" && consumer === "firmware",
);
assert.equal(reservedStimulusEdge?.status, "reserved-not-connected");
assert.match(active.compatibility.verification, /byte-identical v7 copies/);
assert.match(
  active.compatibility.verification,
  /unchanged historical v1, v4, v5, and v6 contract hashes/,
);

console.log(
  `Trio composition v7 semantics: passed (${sha256(activeV7Bytes)})`,
);
