import type { Tone } from "./tone";

interface StatusBadgeProps {
  label: string;
  tone: Tone;
}

/** Small colored pill used for readiness/health/sync status everywhere. */
export default function StatusBadge({ label, tone }: StatusBadgeProps) {
  return <span className={`badge badge-${tone}`}>{label}</span>;
}
