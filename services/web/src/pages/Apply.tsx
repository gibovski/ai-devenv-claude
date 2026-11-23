import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { usePoll } from "../usePoll";

type Run = { id: number; status: string; started_at: string; finished_at?: string; log: string; next_offset: number };

export default function Apply() {
  const preview = usePoll<{ diff: string }>("/api/apply/preview", 0);
  const runs = usePoll<Run[]>("/api/apply/runs", 5000);
  const [runId, setRunId] = useState<number>();
  const [log, setLog] = useState("");
  const [status, setStatus] = useState("");
  const offset = useRef(0);

  useEffect(() => {
    if (!runId) return;
    offset.current = 0;
    setLog("");
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const r = await api<Run>(`/api/apply/runs/${runId}?offset=${offset.current}`);
      offset.current = r.next_offset;
      setLog((l) => l + r.log);
      setStatus(r.status);
      if (r.status === "running") timer = setTimeout(poll, 1000);
      else {
        runs.reload();
        preview.reload();
      }
    };
    poll();
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const apply = async () => setRunId((await api<{ run_id: number }>("/api/apply", { method: "POST" })).run_id);

  return (
    <div className="stack">
      <h1>Apply settings</h1>
      <section className="card">
        <h2>Pending changes</h2>
        <pre className="diff">{preview.data?.diff ?? "Loading…"}</pre>
        <button onClick={apply} disabled={status === "running"}>
          {status === "running" ? "Applying…" : "Apply now"}
        </button>
      </section>
      {runId && (
        <section className="card">
          <h2>
            Run #{runId} <span className={`badge ${status}`}>{status}</span>
          </h2>
          <pre className="log">{log}</pre>
        </section>
      )}
      <section className="card">
        <h2>History</h2>
        <table>
          <tbody>
            {runs.data?.map((r) => (
              <tr key={r.id} onClick={() => setRunId(r.id)} className="clickable">
                <td>#{r.id}</td>
                <td>
                  <span className={`badge ${r.status}`}>{r.status}</span>
                </td>
                <td>{r.started_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
