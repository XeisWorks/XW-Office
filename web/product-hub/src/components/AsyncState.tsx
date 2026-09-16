interface AsyncStateProps {
  loading: boolean;
  error: string | null;
  empty?: boolean;
  emptyLabel?: string;
}

/** Shared loading/error/empty placeholder so pages don't each reinvent it. */
export default function AsyncState({ loading, error, empty, emptyLabel }: AsyncStateProps) {
  if (loading) return <p className="hint">Lädt …</p>;
  if (error) return <p className="hint hint-error">Fehler: {error}</p>;
  if (empty) return <p className="hint">{emptyLabel ?? "Keine Daten."}</p>;
  return null;
}
