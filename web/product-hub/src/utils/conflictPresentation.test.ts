import { describe, expect, it } from "vitest";
import { conflictTypeLabel, displayConflictValue } from "./conflictPresentation";

describe("conflict presentation", () => {
  it("turns mapping state objects into beginner-friendly text", () => {
    expect(displayConflictValue("mapping", {
      state: "not_found",
      external_id: "product_40ea7b33-b5ed-fbb0-d2f0-a4f33fd9aac3",
      error: "product detail fetch returned nothing",
    })).toBe("Produkt bei Wix nicht gefunden · product_40ea7b33-b…d9aac3");
  });

  it("uses a German label for technical conflict types", () => {
    expect(conflictTypeLabel("WRONG_PRODUCT_MAPPING")).toBe("Wix-Verknüpfung stimmt nicht");
  });
});
