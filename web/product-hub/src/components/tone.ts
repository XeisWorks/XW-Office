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
