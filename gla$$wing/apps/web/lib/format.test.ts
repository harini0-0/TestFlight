import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { meterPercent, money } from "./format.ts";

describe("format", () => {
  it("formats dollars", () => {
    assert.equal(money("4200"), "$4,200.00");
  });

  it("caps the threshold meter", () => {
    assert.equal(meterPercent("2400000", "2000000"), 100);
    assert.equal(meterPercent("1000000", "2000000"), 50);
  });
});
