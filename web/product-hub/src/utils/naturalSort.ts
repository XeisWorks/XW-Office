// Natural SKU sort: numeric segments compare numerically, not lexicographically -
// "XW-102" before "XW-1010", "XW-101.1" before "XW-101.10". Mirrors
// services/product_hub/catalog_list.py's `natural_sku_key` exactly (same regex split,
// same "digit run -> number, everything else -> lowercased string" rule) so frontend
// and backend sort orders never disagree if server-side sorting is ever introduced.

const SEGMENT_PATTERN = /(\d+)/;

export function naturalSkuKey(sku: string): (string | number)[] {
  return (sku ?? "")
    .split(SEGMENT_PATTERN)
    .filter((part) => part !== "")
    .map((part) => (/^\d+$/.test(part) ? Number(part) : part.toLowerCase()));
}

export function compareNatural(a: string, b: string): number {
  const left = naturalSkuKey(a);
  const right = naturalSkuKey(b);
  const length = Math.max(left.length, right.length);
  for (let i = 0; i < length; i += 1) {
    const l = left[i];
    const r = right[i];
    if (l === undefined) return -1;
    if (r === undefined) return 1;
    if (typeof l === "number" && typeof r === "number") {
      if (l !== r) return l - r;
      continue;
    }
    const ls = String(l);
    const rs = String(r);
    if (ls !== rs) return ls < rs ? -1 : 1;
  }
  return 0;
}
