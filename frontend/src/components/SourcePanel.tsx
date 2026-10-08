import { useEffect, useRef } from "react";
import type { SourceRef } from "../api";
import { sourcePath } from "../labels";

export interface SourceSelection {
  label: string;
  display: string;
  source: SourceRef;
}

export default function SourcePanel({ selection, onClose }: { selection: SourceSelection | null; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (selection) closeRef.current?.focus();
  }, [selection]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!selection) return null;
  const s = selection.source;
  return (
    <aside className="source-panel" aria-label="Source record">
      <div className="source-head">
        <span className="source-tag">{selection.label}</span>
        <button ref={closeRef} className="link" onClick={onClose}>Close</button>
      </div>
      <p className="source-path">{sourcePath(s)}</p>
      <dl className="source-meta">
        {s.recorded_on && (<><dt>Date</dt><dd>{s.recorded_on}</dd></>)}
        {s.encounter_id && (<><dt>Encounter</dt><dd>{s.encounter_id}</dd></>)}
        {s.page && (<><dt>Page</dt><dd>{s.page}</dd></>)}
      </dl>
      <blockquote className="source-text">{selection.display}</blockquote>
      <p className="fine">Read-only copy of the Meditab record. Open it in Meditab to change it.</p>
    </aside>
  );
}
