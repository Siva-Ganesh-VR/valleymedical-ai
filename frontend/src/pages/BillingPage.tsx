import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, features, type CaseSummary } from "../api";
import { ActionError, LoadState, Notice, Pill } from "../components/ui";
import { useAction, useLoad } from "../hooks";
import { CATEGORY_LABELS, FLAG_LABELS, money, STATE_LABELS, stateTone } from "../labels";
import { useSession } from "../session";

const VIEWS: { key: string; label: string; match: (c: CaseSummary) => boolean }[] = [
  { key: "person", label: "Needs a person", match: (c) => stateTone(c.state) === "human" },
  { key: "escalated", label: "Escalated", match: (c) => c.state === "ESCALATED" },
  { key: "owner", label: "With owner", match: (c) => c.state === "ROUTED" || c.state === "SUBMITTED_BY_STAFF" },
  { key: "done", label: "Done", match: (c) => c.state === "COMPLETED" || c.state === "NO_ACTION" },
  { key: "all", label: "All", match: () => true },
];
// Order a case moves through the workflow; used for the status bar.
const STATUS_ORDER = [
  "AWAITING_CLASSIFICATION_REVIEW", "AWAITING_DRAFT_APPROVAL", "DRAFT_REJECTED", "ROUTED",
  "SUBMITTED_BY_STAFF", "ESCALATED", "COMPLETED", "NO_ACTION", "IDENTIFIED",
];

const SORTS: Record<string, { label: string; fn: (a: CaseSummary, b: CaseSummary) => number }> = {
  claim: { label: "Claim number", fn: (a, b) => a.claim_id.localeCompare(b.claim_id) },
  amount: { label: "Billed, highest first", fn: (a, b) => b.billed_amount - a.billed_amount },
  oldest: { label: "Service date, oldest first", fn: (a, b) => a.date_of_service.localeCompare(b.date_of_service) },
};

export default function BillingPage() {
  const navigate = useNavigate();
  const { user } = useSession();
  const queues = useLoad(() => api.queues(), []);
  const [queue, setQueue] = useState<string>("");
  useEffect(() => {
    if (!queue && queues.data?.length) setQueue(queues.data[0]);
  }, [queues.data, queue]);
  const cases = useLoad(() => (queue ? api.cases(queue) : Promise.resolve([])), [queue]);
  const sync = useAction();
  const [syncNote, setSyncNote] = useState<string | null>(null);
  const canWork = user.role === "biller" || user.role === "billing_approver";
  const [view, setView] = useState("person");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [sort, setSort] = useState("claim");
  const [status, setStatus] = useState("");
  const canSeed = user.role === "billing_approver" || user.role === "admin";
  const seed = useAction();
  const loadDemo = () => seed.run(async () => {
    const r = await features.demoWorkload(queue);
    setSyncNote(r.moved.length
      ? `Demo workload loaded: ${r.moved.length} cases moved into different statuses. Their decisions are excluded from Billing insights.`
      : "Demo workload already loaded. Nothing to change.");
    setView("all");
    setStatus("");
    await cases.reload();
  });
  const all = cases.data ?? [];
  const counts = useMemo(() => Object.fromEntries(VIEWS.map((v) => [v.key, all.filter(v.match).length])), [all]);
  const statusCounts = useMemo(() => {
    const out: Record<string, number> = {};
    all.forEach((c) => { out[c.state] = (out[c.state] ?? 0) + 1; });
    return STATUS_ORDER.filter((s) => out[s]).map((s) => ({ state: s, count: out[s] }));
  }, [all]);
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    const match = VIEWS.find((v) => v.key === view)!.match;
    return all
      .filter(status ? (c) => c.state === status : match)
      .filter((c) => !category || c.category === category)
      .filter((c) => !q || `${c.claim_id} ${c.payer} ${c.denial_code ?? ""} ${c.owner ?? ""}`.toLowerCase().includes(q))
      .sort(SORTS[sort].fn);
  }, [all, view, search, category, sort, status]);
  const categories = useMemo(() => Array.from(new Set(all.map((c) => c.category).filter(Boolean))) as string[], [all]);
  const totalAtStake = shown.reduce((sum, c) => sum + c.billed_amount, 0);

  const pull = () =>
    sync.run(async () => {
      const r = await api.sync(queue);
      setSyncNote(`${r.created} new case${r.created === 1 ? "" : "s"}, ${r.already_open} already open, ${r.no_action} need no action.`);
      await cases.reload();
    });

  if (queues.error || !queues.data) return <LoadState loading={queues.loading} error={queues.error} />;

  const waiting = (cases.data ?? []).filter((c) => stateTone(c.state) === "human").length;

  return (
    <section>
      <header className="page-head">
        <h1>Billing work</h1>
        <p className="lede">The agent classifies claims, gathers records and drafts letters. People confirm every classification and approve every draft. Nothing is sent from here.</p>
      </header>
      <div className="toolbar">
        <label>
          Work queue{" "}
          <select value={queue} onChange={(e) => setQueue(e.target.value)}>
            {queues.data.map((q) => <option key={q} value={q}>{q}</option>)}
          </select>
        </label>
        {canWork && (
          <button className="primary" disabled={!queue || sync.busy} onClick={pull}>
            {sync.busy ? "Reading queue…" : "Read work queue"}
          </button>
        )}
        {canSeed && (
          <button disabled={!queue || seed.busy} onClick={loadDemo} title="Moves synthetic cases through the real agent into a mix of statuses">
            {seed.busy ? "Loading…" : "Load demo workload"}
          </button>
        )}
        {syncNote && <span className="fine">{syncNote}</span>}
      </div>
      <ActionError message={sync.error ?? seed.error} />
      {waiting > 0 && <Notice tone="human" title={`${waiting} case${waiting > 1 ? "s" : ""} waiting for a person`} />}
      <LoadState loading={cases.loading && !cases.data} error={cases.error} />
      {cases.data && cases.data.length === 0 && (
        <p className="empty">No cases yet. {canWork ? "Read the work queue to start." : "Ask billing staff to read the work queue."}</p>
      )}
      {all.length > 0 && (
        <>
          <div className="status-bar" aria-label="Cases by status">
            {statusCounts.map(({ state, count }) => (
              <button key={state} className={`status-tile tone-${stateTone(state)}${status === state ? " active" : ""}`}
                      aria-pressed={status === state} onClick={() => setStatus(status === state ? "" : state)}>
                <span className="status-count">{count}</span>
                <span className="status-name">{STATE_LABELS[state] ?? state}</span>
              </button>
            ))}
          </div>
          <div className="views" role="tablist" aria-label="Filter cases">
            {VIEWS.map((v) => (
              <button key={v.key} role="tab" aria-selected={!status && view === v.key} className={`view-chip${!status && view === v.key ? " active" : ""}`} onClick={() => { setStatus(""); setView(v.key); }}>
                {v.label} <span className="count">{counts[v.key]}</span>
              </button>
            ))}
          </div>
          <div className="toolbar">
            <input type="search" aria-label="Search cases" placeholder="Search claim, payer, code or owner" value={search} onChange={(e) => setSearch(e.target.value)} />
            <label>Status <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Any</option>
              {statusCounts.map(({ state, count }) => <option key={state} value={state}>{STATE_LABELS[state] ?? state} ({count})</option>)}
            </select></label>
            <label>Category <select value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">All</option>
              {categories.sort().map((c) => <option key={c} value={c}>{CATEGORY_LABELS[c] ?? c}</option>)}
            </select></label>
            <label>Sort <select value={sort} onChange={(e) => setSort(e.target.value)}>
              {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select></label>
            <span className="fine">Showing {shown.length} of {all.length} · {money(totalAtStake)} billed</span>
          </div>
        </>
      )}
      {all.length > 0 && shown.length === 0 && <p className="empty">No cases match these filters.</p>}
      {shown.length > 0 && (
        <table className="table clickable">
          <thead>
            <tr><th>Claim</th><th>Payer</th><th>Service date</th><th className="num">Billed</th><th>Category</th><th>Status</th><th>Owner</th></tr>
          </thead>
          <tbody>
            {shown.map((c) => (
              <tr key={c.id} onClick={() => navigate(`/billing/cases/${c.id}`)} tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && navigate(`/billing/cases/${c.id}`)}>
                <td><strong>{c.claim_id}</strong>{c.denial_code && <span className="fine"> code {c.denial_code}</span>}</td>
                <td>{c.payer}</td>
                <td className="num">{c.date_of_service}</td>
                <td className="num">{money(c.billed_amount)}</td>
                <td>
                  {c.category ? CATEGORY_LABELS[c.category] ?? c.category : "None"}
                  {c.category && !c.category_confirmed && <span className="fine"> (proposed)</span>}
                  {c.flags.map((f) => <div key={f} className="flag">{FLAG_LABELS[f] ?? f}</div>)}
                </td>
                <td><Pill tone={stateTone(c.state)}>{STATE_LABELS[c.state] ?? c.state}</Pill></td>
                <td>{c.owner ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
