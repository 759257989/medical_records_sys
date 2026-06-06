// frontend/src/auth/AuthContext.tsx
import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import api from "../api/client";

type User = { id: string; email: string; role: string; first_name: string; last_name: string };
type AuthCtx = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const Ctx = createContext<AuthCtx>(null!);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // 首次加载：若本地有 token，调 /me 恢复登录态（顺便验证 token）
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) { setLoading(false); return; }
    api.get("/auth/me")
      .then((r) => setUser(r.data))
      .catch(() => localStorage.removeItem("token"))
      .finally(() => setLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    const r = await api.post("/auth/login", { email, password });
    localStorage.setItem("token", r.data.access_token);
    setUser(r.data.user);
  };

  const logout = () => { localStorage.removeItem("token"); setUser(null); };

  return <Ctx.Provider value={{ user, loading, login, logout }}>{children}</Ctx.Provider>;
}