// frontend/src/auth/AuthContext.tsx
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import api from "../api/client";

type User = { id: string; email: string; role: string; first_name: string; last_name: string };
type AuthCtx = {
  user: User | null;
  loading: boolean;
  sessionExpired: boolean;                                   // ← 新增
  login: (email: string, password: string) => Promise<User>;
  logout: () => void;
};

const Ctx = createContext<AuthCtx>(null!);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [sessionExpired, setSessionExpired] = useState(false);   // ← 新增

  // 首次加载：若本地有 token，调 /me 恢复登录态（顺便验证 token）
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) { setLoading(false); return; }
    api.get("/auth/me")
      .then((r) => setUser(r.data))
      .catch(() => localStorage.removeItem("token"))
      .finally(() => setLoading(false));
  }, []);

  // 监听全局「会话过期」事件（由 axios 拦截器 / SSE 流在收到 401 时广播）
  // 注意：只置标志位、【不清空 user】——保留 user 才能让当前页面（含未保存草稿）不被卸载
  useEffect(() => {
    const onExpired = () => setSessionExpired(true);
    window.addEventListener("session-expired", onExpired);
    return () => window.removeEventListener("session-expired", onExpired);
  }, []);

  const login = async (email: string, password: string): Promise<User> => {
    const r = await api.post("/auth/login", { email, password });
    localStorage.setItem("token", r.data.access_token);
    setUser(r.data.user);
    setSessionExpired(false);   // 重登成功 → 关闭过期态 → 弹窗自动消失
    return r.data.user as User;
  };

  const logout = () => { localStorage.removeItem("token"); setUser(null); setSessionExpired(false); };

  return (
    <Ctx.Provider value={{ user, loading, sessionExpired, login, logout }}>
      {children}
    </Ctx.Provider>
  );
}
