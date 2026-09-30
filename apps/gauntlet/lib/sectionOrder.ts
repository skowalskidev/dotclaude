// Shared display order: work in progress floats to the top, without touching plan order.
import type { Section, SectionStatus } from './types';

const RANK: Record<SectionStatus, number> = { review: 0, doing: 1, blocked: 2, todo: 3, done: 4 };

/** Sections ranked review, doing, blocked, todo, done; plan order preserved inside each rank.
 * Never mutates or reorders the caller's array — the plan's sections stay the source of truth. */
export function displayOrder(sections: Section[]): Section[] {
  return sections
    .map((s, i) => ({ s, i }))
    .sort((a, b) => RANK[a.s.status] - RANK[b.s.status] || a.i - b.i)
    .map((x) => x.s);
}
