import type { ChatCitation } from "@/lib/types";

/**
 * Structural subset shared by ChatCitation and KnowledgeCitation so the
 * grouping helper works for every citation list in the app.
 */
interface CitationLike {
  chunk_id: string;
  document_id: string;
  document_title: string;
  version_number: number;
  page: number | null;
  section_title: string | null;
}

/**
 * A citation chip is one per document (not per chunk), carrying the [N]
 * markers it covers. The [N] numbers in the assistant's answer map 1:1 to
 * the citations array order (see GroundingContextBuilder), so the chips can
 * show exactly which evidence blocks the answer references.
 */
export interface CitationGroup<T extends CitationLike = ChatCitation> {
  documentId: string;
  title: string;
  markers: string;
  citations: { marker: number; citation: T }[];
}

function formatMarkers(markers: number[]): string {
  const sorted = [...markers].sort((a, b) => a - b);
  if (sorted.length === 0) return "";
  const ranges: string[] = [];
  let start = sorted[0];
  let prev = sorted[0];
  for (let i = 1; i <= sorted.length; i++) {
    const cur = sorted[i];
    if (cur !== prev + 1) {
      ranges.push(start === prev ? `${start}` : `${start}–${prev}`);
      start = cur;
    }
    prev = cur;
  }
  return ranges.join(", ");
}

export function groupCitations<T extends CitationLike>(
  citations: T[]
): CitationGroup<T>[] {
  const groups: CitationGroup<T>[] = [];
  const byDoc = new Map<string, { title: string; items: { marker: number; citation: T }[] }>();
  citations.forEach((citation, index) => {
    const marker = index + 1;
    let group = byDoc.get(citation.document_id);
    if (!group) {
      group = { title: citation.document_title, items: [] };
      byDoc.set(citation.document_id, group);
    }
    group.items.push({ marker, citation });
  });
  for (const [documentId, group] of byDoc) {
    groups.push({
      documentId,
      title: group.title,
      markers: formatMarkers(group.items.map((i) => i.marker)),
      citations: group.items,
    });
  }
  return groups;
}

/**
 * The [N] markers actually referenced by an answer, tolerating the prompt's
 * "cite every claim" forms: "[1]", "[2, 3]", "[1–5]", "([1]–[5])".
 */
export function citedMarkers(text: string): Set<number> {
  const markers = new Set<number>();
  const re = /\[([0-9][0-9,\s–-]*)\]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    for (const token of m[1].split(/[^\d]+/)) {
      if (token) markers.add(Number(token));
    }
  }
  // Expand dash ranges, both "[1–5]" inside one bracket and "([1]–[5])"
  // across adjacent brackets: a dash between markers means the whole range.
  const rangeRe = /(\d{1,3})\s*\]?\s*[–—-]\s*\[?\s*(\d{1,3})/g;
  while ((m = rangeRe.exec(text)) !== null) {
    const start = Number(m[1]);
    const end = Number(m[2]);
    if (start < end) {
      for (let i = start; i <= end; i++) markers.add(i);
    }
  }
  return markers;
}

/**
 * Keep only citations whose [N] marker appears in the answer text, so chips
 * show exactly what the answer references — never the full retrieval set.
 * When the text carries no markers at all, nothing was cited: return [].
 */
export function filterCited<T extends CitationLike>(
  citations: T[],
  text: string | null | undefined
): T[] {
  if (!text) return [];
  const used = citedMarkers(text);
  if (used.size === 0) return [];
  return citations.filter((_, index) => used.has(index + 1));
}
