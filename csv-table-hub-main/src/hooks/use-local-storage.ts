import { useCallback, useEffect, useRef, useState } from "react";

const KEY = "csv-migrator:jobs:v1";

export function useLocalStorageState<T>(defaultValue: T): [T, (updater: T | ((prev: T) => T)) => void, () => void] {
  const [state, setState] = useState<T>(defaultValue);
  const hydrated = useRef(false);

  useEffect(() => {
    try {
      const raw = typeof window !== "undefined" ? window.localStorage.getItem(KEY) : null;
      if (raw) setState(JSON.parse(raw) as T);
    } catch {
      /* ignore */
    }
    hydrated.current = true;
  }, []);

  useEffect(() => {
    if (!hydrated.current) return;
    try {
      window.localStorage.setItem(KEY, JSON.stringify(state));
    } catch {
      /* ignore quota */
    }
  }, [state]);

  const update = useCallback((updater: T | ((prev: T) => T)) => {
    setState((prev) => (typeof updater === "function" ? (updater as (p: T) => T)(prev) : updater));
  }, []);

  const clear = useCallback(() => {
    try {
      window.localStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
  }, []);

  return [state, update, clear];
}
