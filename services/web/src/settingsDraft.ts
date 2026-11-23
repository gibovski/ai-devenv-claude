import type { SettingsT } from "./types";

/** Unsaved Settings edits, kept in memory while you move between pages so they are not lost, and so the
 *  Apply page can warn that Apply uses the saved settings, not these. Never written to browser storage
 *  because pending secrets may be in it. */
export type Draft = { settings: SettingsT; pending: Record<string, string> };

let draft: Draft | null = null;

export const getDraft = (): Draft | null => draft;
export const setDraft = (d: Draft | null): void => {
  draft = d;
};
