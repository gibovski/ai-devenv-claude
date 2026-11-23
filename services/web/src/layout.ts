export type GNode = { id: number; title: string; status: string; state: string; repo: string; complexity?: string; model?: string };
export type GEdge = { from: number; to: number };
export type Placed = GNode & { x: number; y: number; layer: number };

/** Layer nodes by longest path from a root (dependencies on the left), then order each layer
 *  by the average position of its parents to reduce crossings. */
export function layout(nodes: GNode[], edges: GEdge[], colW = 230, rowH = 64): { placed: Placed[]; width: number; height: number } {
  const parents = new Map<number, number[]>();
  nodes.forEach((n) => parents.set(n.id, []));
  edges.forEach((e) => parents.get(e.to)?.push(e.from));
  const layer = new Map<number, number>();
  const visiting = new Set<number>();
  const depth = (id: number): number => {
    if (layer.has(id)) return layer.get(id)!;
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const ps = parents.get(id) ?? [];
    const d = ps.length ? Math.max(...ps.map(depth)) + 1 : 0;
    visiting.delete(id);
    layer.set(id, d);
    return d;
  };
  nodes.forEach((n) => depth(n.id));
  const layers: GNode[][] = [];
  nodes.forEach((n) => (layers[layer.get(n.id)!] ??= []).push(n));
  const row = new Map<number, number>();
  layers.forEach((ns) => {
    ns.sort((a, b) => {
      const avg = (n: GNode) => {
        const ps = (parents.get(n.id) ?? []).map((p) => row.get(p) ?? 0);
        return ps.length ? ps.reduce((x, y) => x + y, 0) / ps.length : n.id;
      };
      return avg(a) - avg(b) || a.id - b.id;
    });
    ns.forEach((n, i) => row.set(n.id, i));
  });
  const placed = nodes.map((n) => ({ ...n, layer: layer.get(n.id)!, x: 20 + layer.get(n.id)! * colW, y: 20 + row.get(n.id)! * rowH }));
  const width = 40 + layers.length * colW;
  const height = 40 + Math.max(1, ...layers.map((l) => l.length)) * rowH;
  return { placed, width, height };
}
