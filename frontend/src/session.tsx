import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { DEMO_USERS, setApiUser, type DemoUser } from "./api";

interface SessionValue {
  user: DemoUser;
  switchUser: (username: string) => void;
}

const SessionContext = createContext<SessionValue | null>(null);
const KEY = "vm-poc-demo-user";

function initialUser(): DemoUser {
  const saved = typeof sessionStorage !== "undefined" ? sessionStorage.getItem(KEY) : null;
  return DEMO_USERS.find((u) => u.username === saved) ?? DEMO_USERS[0];
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<DemoUser>(() => {
    const u = initialUser();
    setApiUser(u);
    return u;
  });

  useEffect(() => setApiUser(user), [user]);

  const switchUser = useCallback((username: string) => {
    const next = DEMO_USERS.find((u) => u.username === username);
    if (!next) return;
    setApiUser(next);
    sessionStorage.setItem(KEY, next.username);
    setUser(next);
  }, []);

  return <SessionContext.Provider value={{ user, switchUser }}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside SessionProvider");
  return ctx;
}
