export type Tone = "ok" | "warn" | "bad" | "neutral";

export function readinessTone(ready: boolean): Tone {
  return ready ? "ok" : "warn";
}

export function healthTone(status: string): Tone {
  switch (status) {
    case "ok":
      return "ok";
    case "unknown":
      return "neutral";
    case "stale":
      return "warn";
    default:
      return "bad";
  }
}

export function syncTone(status: string): Tone {
  switch (status) {
    case "synced":
      return "ok";
    case "never":
    case "disabled":
      return "neutral";
    case "pending":
      return "warn";
    default:
      return "bad";
  }
}

/** ✓/!/○/— per the build request's channel-state legend - "not_applicable" is a
 * deliberate, non-error state (e.g. a sevdesk-only line item was never meant to have
 * a Wix listing), never rendered as a defect. */
export function channelStateTone(state: string): Tone {
  switch (state) {
    case "synced":
      return "ok";
    case "error":
      return "bad";
    case "pending":
      return "warn";
    default:
      return "neutral";
  }
}

export function channelStateSymbol(state: string): string {
  switch (state) {
    case "synced":
      return "✓";
    case "error":
      return "!";
    case "pending":
      return "○";
    default:
      return "—";
  }
}
