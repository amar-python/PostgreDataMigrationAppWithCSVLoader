import { useCallback, useEffect, useRef, useState } from "react";
import { dropUnscoped, userKey } from "@/lib/user-storage";

const BASE = "csv-migrator:jobs:v1";

export function useLocalStorageState<T>(defaultValue: T): [T, (updater: T | ((prev: T) => T)) => void, () => void] {
  const [state, setState] = useState<T>(defaultValue);
  const hydrated = useRef(false);
  // The signed-in user's key, read once on mount (#176); null when nobody is signed in, so nothing is stored.
  const key = useRef<string | null>(null);

  useEffect(() => {
    try {
      dropUnscoped(BASE);
      key.current = userKey(BASE);
      const raw = key.current ? window.localStorage.getItem(key.current) : null;
      if (raw) setState(JSON.parse(raw) as T);
    } catch {
      /* ignore */
    }
    hydrated.current = true;
  }, []);

  useEffect(() => {
    if (!hydrated.current || !key.current) return;
    try {
      window.localStorage.setItem(key.current, JSON.stringify(state));
    } catch {
      /* ignore quota */
    }
  }, [state]);

  const update = useCallback((updater: T | ((prev: T) => T)) => {
    setState((prev) => (typeof updater === "function" ? (updater as (p: T) => T)(prev) : updater));
  }, []);

  const clear = useCallback(() => {
    try {
      if (key.current) window.localStorage.removeItem(key.current);
    } catch {
      /* ignore */
    }
  }, []);

  return [state, update, clear];
}
