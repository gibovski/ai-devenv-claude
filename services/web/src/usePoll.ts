import { useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Fetch a JSON endpoint now and every `ms` milliseconds. */
export function usePoll<T>(path: string | null, ms = 3000): { data: T | undefined; error: string | undefined; reload: () => void } {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string>();
  const [tick, setTick] = useState(0);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    if (!path) return;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const d = await api<T>(path);
        if (alive.current) {
          setData(d);
          setError(undefined);
        }
      } catch (e) {
        if (alive.current) setError((e as Error).message);
      }
      if (alive.current && ms > 0) timer = setTimeout(load, ms);
    };
    load();
    return () => {
      alive.current = false;
      clearTimeout(timer);
    };
  }, [path, ms, tick]);
  return { data, error, reload: () => setTick((t) => t + 1) };
}
