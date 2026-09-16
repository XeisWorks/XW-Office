import { useEffect, useState, type DependencyList } from "react";
import { ApiError } from "../api/client";

interface UseApiResult<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

/**
 * Fetch-on-mount/deps-change helper for the read-only pages. `onUnauthorized`
 * is called (never surfaced as a page-level error) whenever any call returns
 * 401, so a stale/cleared token bounces the whole app back to the token gate
 * instead of showing a confusing per-widget error.
 */
export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: DependencyList,
  onUnauthorized: () => void,
): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetcher()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          onUnauthorized();
          return;
        }
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // deps is caller-controlled on purpose: fetcher/onUnauthorized are re-created
    // every render, including them would re-fetch on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading };
}
