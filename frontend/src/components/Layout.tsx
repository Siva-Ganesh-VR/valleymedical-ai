import { type ReactNode, useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { api, DEMO_USERS } from "../api";
import { useSession } from "../session";

const NAV = [
  { to: "/patients", label: "Patients", hint: "Meditab records" },
  { to: "/billing", label: "Billing work", hint: "Denials and follow-up" },
  { to: "/exceptions", label: "Exceptions", hint: "Needs a person" },
  { to: "/audit", label: "Audit log", hint: "Who saw what" },
];

export default function Layout({ children }: { children: ReactNode }) {
  const { user, switchUser } = useSession();
  const [llm, setLlm] = useState<string | null>(null);

  useEffect(() => {
    api.health().then((h) => setLlm(h.llm)).catch(() => setLlm(null));
  }, []);

  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand">
          <span className="brand-name">Valley Medical</span>
          <span className="brand-sub">AI platform, proof of concept</span>
        </div>
        <nav aria-label="Main">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
              <span>{n.label}</span>
              <small>{n.hint}</small>
            </NavLink>
          ))}
        </nav>
        <div className="rail-foot">
          <label htmlFor="user-switch">Signed in as</label>
          <select id="user-switch" value={user.username} onChange={(e) => switchUser(e.target.value)}>
            {DEMO_USERS.map((u) => (
              <option key={u.username} value={u.username}>
                {u.label}
              </option>
            ))}
          </select>
          <p className="fine">
            Synthetic data only. Meditab and billing are simulated.
            {llm && <> Model: {llm === "mock" ? "offline mock" : "Claude API"}.</>}
          </p>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
