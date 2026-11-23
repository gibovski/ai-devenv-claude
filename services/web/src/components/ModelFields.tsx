import { usePoll } from "../usePoll";
import type { Catalogue } from "../types";

export type ModelChoice = { complexity: string; model: string; effort: string };

const EFFORTS = ["low", "medium", "high", "xhigh", "max"];

export function useCatalogue(): Catalogue | undefined {
  return usePoll<Catalogue>("/api/models", 0).data;
}

/** One line such as "medium → claude-sonnet-5-5 / gpt-5-codex · high effort" for a task. */
export function modelSummary(t: ModelChoice, cat?: Catalogue): string {
  const level = t.complexity && cat?.complexity?.[t.complexity];
  const model = t.model || (level ? `${level.anthropic} / ${level.openai}` : "");
  const effort = t.effort || (level ? level.effort : "");
  if (!t.complexity && !t.model) return t.effort ? `Settings model · ${t.effort} effort` : "Settings model";
  return [t.complexity, model].filter(Boolean).join(" → ") + (effort ? ` · ${effort} effort` : "");
}

/** Complexity, model override and effort selects. Empty values mean "decide from the rating" or Settings. */
export function ModelFields({ value, onChange }: { value: ModelChoice; onChange: (v: ModelChoice) => void }) {
  const cat = useCatalogue();
  const levels = Object.entries(cat?.complexity ?? {});
  const set = (k: keyof ModelChoice) => (e: { target: { value: string } }) => onChange({ ...value, [k]: e.target.value });
  return (
    <div className="grid3">
      <label>
        Complexity
        <select value={value.complexity} onChange={set("complexity")}>
          <option value="">Not rated (Settings model)</option>
          {levels.map(([id, l]) => (
            <option key={id} value={id} title={l.when}>
              {l.label}: {l.anthropic} / {l.openai}
            </option>
          ))}
        </select>
      </label>
      <label>
        Model override
        <select value={value.model} onChange={set("model")}>
          <option value="">From the complexity</option>
          <optgroup label="Claude agents">
            {(cat?.anthropic ?? []).map((m) => (
              <option key={m.id} value={m.id}>
                {m.label} ({m.usage} usage)
              </option>
            ))}
          </optgroup>
          <optgroup label="Codex agents">
            {(cat?.openai ?? []).map((m) => (
              <option key={m.id} value={m.id}>
                {m.label} ({m.usage} usage)
              </option>
            ))}
          </optgroup>
          {value.model && ![...(cat?.anthropic ?? []), ...(cat?.openai ?? [])].some((m) => m.id === value.model) && (
            <option value={value.model}>{value.model}</option>
          )}
        </select>
      </label>
      <label>
        Effort
        <select value={value.effort} onChange={set("effort")}>
          <option value="">From the complexity</option>
          {EFFORTS.map((e) => (
            <option key={e} value={e}>
              {e}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
