import type { ReactNode } from "react";
import type { ApiError } from "../api";
import type { Tone } from "../labels";

export function Pill({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`pill pill-${tone}`}>{children}</span>;
}

export function Notice({ tone, title, children }: { tone: "human" | "critical" | "info"; title: string; children?: ReactNode }) {
  return (
    <div className={`notice notice-${tone}`} role={tone === "critical" ? "alert" : "status"}>
      <strong>{title}</strong>
      {children && <div>{children}</div>}
    </div>
  );
}

export function LoadState({ loading, error }: { loading: boolean; error: ApiError | null }) {
  if (error) {
    if (error.status === 403)
      return <Notice tone="info" title="Your role can't open this page">{error.message}. Switch user in the menu to continue.</Notice>;
    return <Notice tone="critical" title="Couldn't load this page">{error.message}</Notice>;
  }
  if (loading) return <p className="loading">Loading…</p>;
  return null;
}

export function ActionError({ message }: { message: string | null }) {
  return message ? <p className="action-error" role="alert">{message}</p> : null;
}
