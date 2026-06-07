// frontend/src/api/client.ts
//
// 全局 axios 实例。所有页面的 API 请求都通过这个 api 对象发出。
import axios from "axios";

const api = axios.create({ baseURL: "/api" });

// ── 请求拦截器：自动带上 JWT ────────────────────────────────────────────────
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// ── 响应拦截器：优雅处理 401（会话过期 / 被停用）────────────────────────────
api.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status;
    const url: string = err.config?.url ?? "";
    // 登录接口自己的 401/403 由 LoginPage / 重登弹窗内联处理，不触发全局逻辑，
    // 否则重登输错密码会把自己的弹窗又触发一遍。
    const isAuthCall = url.includes("/auth/login");

    if (status === 401 && !isAuthCall) {
      // 关键：清掉失效 token，但【绝不做 location.href 硬跳转】。
      // 硬跳转会卸载整棵 React 树，把医生还没保存的 SOAP 一起冲掉（EDGE-2 数据丢失根因）。
      // 改为广播事件，交给 AuthContext 弹「就地重登」窗口——页面不卸载，内存草稿不丢。
      localStorage.removeItem("token");
      window.dispatchEvent(new CustomEvent("session-expired"));
    }
    return Promise.reject(err); // 其他错误继续向上抛，由业务代码处理
  }
);

export default api;