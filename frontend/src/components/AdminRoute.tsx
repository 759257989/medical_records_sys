// frontend/src/components/AdminRoute.tsx
import type { JSX } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function AdminRoute({ children }: { children: JSX.Element }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="center">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;       // 未登录 → 登录页
  if (user.role !== "admin") return <Navigate to="/" replace />; // 非 admin → 回首页
  return children;
}