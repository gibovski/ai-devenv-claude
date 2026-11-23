import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { layout, type GEdge, type GNode } from "../layout";
import { usePoll } from "../usePoll";

const FILL: Record<string, string> = {
  ready: "#dcfce7",
  blocked: "#fef3c7",
  in_progress: "#dbeafe",
  in_review: "#dbeafe",
  deploying: "#dbeafe",
  done: "#e5e7eb",
  needs_human: "#fee2e2",
  failed: "#fee2e2",
  cancelled: "#f3f4f6",
};
const STROKE: Record<string, string> = { ready: "#15803d", blocked: "#b45309", needs_human: "#b91c1c", in_progress: "#1d4ed8", in_review: "#1d4ed8", deploying: "#1d4ed8" };
const W = 200;
const H = 44;

export default function Graph() {
  const [showDone, setShowDone] = useState(false);
  const { data } = usePoll<{ nodes: GNode[]; edges: GEdge[] }>(`/api/graph?include_done=${showDone}`, 5000);
  const nav = useNavigate();
  if (!data) return <p>Loading…</p>;
  const { placed, width, height } = layout(data.nodes, data.edges);
  const pos = new Map(placed.map((p) => [p.id, p]));
  return (
    <div className="stack">
      <h1>Dependency graph</h1>
      <div className="actions">
        <label className="inline">
          <input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} /> Show done tasks
        </label>
        <span className="muted small">Arrows point from a dependency to the task waiting on it. Click a task for details.</span>
      </div>
      <div className="actions small">
        {Object.keys(FILL).map((k) => (
          <span key={k} className="badge" style={{ background: FILL[k], color: "#1d2330" }}>
            {k.replace("_", " ")}
          </span>
        ))}
      </div>
      {placed.length === 0 ? (
        <p className="muted">No tasks to show.</p>
      ) : (
        <div className="card" style={{ overflow: "auto" }}>
          <svg width={width} height={height} role="img" aria-label="Task dependency graph">
            <defs>
              <marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#9ca3af" />
              </marker>
            </defs>
            {data.edges.map((e) => {
              const a = pos.get(e.from);
              const b = pos.get(e.to);
              if (!a || !b) return null;
              const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2;
              const mx = (x1 + x2) / 2;
              return <path key={`${e.from}-${e.to}`} d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`} fill="none" stroke="#9ca3af" markerEnd="url(#arrow)" />;
            })}
            {placed.map((n) => (
              <g key={n.id} transform={`translate(${n.x},${n.y})`} style={{ cursor: "pointer" }} onClick={() => nav(`/tasks/${n.id}`)}>
                <title>{`#${n.id} ${n.title}\n${n.state}${n.repo ? `\n${n.repo}` : ""}`}</title>
                <rect width={W} height={H} rx={8} fill={FILL[n.state] ?? "#fff"} stroke={STROKE[n.state] ?? "#9ca3af"} />
                <text x={10} y={18} fontSize={12} fontWeight={600} style={{ fill: "#1d2330" }}>
                  #{n.id} {n.state.replace("_", " ")}
                </text>
                <text x={10} y={34} fontSize={12} style={{ fill: "#1d2330" }}>
                  {n.title.length > 28 ? n.title.slice(0, 27) + "…" : n.title}
                </text>
              </g>
            ))}
          </svg>
        </div>
      )}
    </div>
  );
}
