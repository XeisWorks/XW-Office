import { describe, expect, it } from "vitest";
import { compareNatural, naturalSkuKey } from "./naturalSort";

describe("compareNatural", () => {
  it("orders numeric segments numerically, not lexicographically", () => {
    const skus = ["XW-101.10", "XW-101.2", "XW-101.1", "XW-1010", "XW-102", "XW-101"];
    expect([...skus].sort(compareNatural)).toEqual([
      "XW-101",
      "XW-101.1",
      "XW-101.2",
      "XW-101.10",
      "XW-102",
      "XW-1010",
    ]);
  });

  it("matches the acceptance example from the build request", () => {
    const skus = ["XW-102.5-D", "XW-4043", "XW-101.2", "XW-102", "XW-4001", "XW-101.1", "XW-4516", "XW-101", "XW-102.5"];
    expect([...skus].sort(compareNatural)).toEqual([
      "XW-101",
      "XW-101.1",
      "XW-101.2",
      "XW-102",
      "XW-102.5",
      "XW-102.5-D",
      "XW-4001",
      "XW-4043",
      "XW-4516",
    ]);
  });

  it("is stable for equal keys", () => {
    expect(compareNatural("XW-1", "XW-1")).toBe(0);
  });
});

describe("naturalSkuKey", () => {
  it("splits digit runs into numbers and keeps the rest as lowercased strings", () => {
    expect(naturalSkuKey("XW-102.5-D")).toEqual(["xw-", 102, ".", 5, "-d"]);
  });

  it("handles an empty string without throwing", () => {
    expect(naturalSkuKey("")).toEqual([]);
  });
});
