// frontend/src/api/client.ts
//
// 全局 axios 实例。所有页面的 API 请求都通过这个 api 对象发出，
// 而不是直接用 axios，这样认证逻辑只需在这里写一次。

import axios from "axios";

// baseURL="/api" 配合 vite.config.ts 里的代理规则：
// 浏览器发出的 /api/xxx 请求会被 Vite dev server 转发到 http://localhost:8000/api/xxx
// 这样前端代码里不需要写死后端地址，生产环境换 nginx 代理也无需改代码
const api = axios.create({ baseURL: "/api" });

// ── 请求拦截器 ──────────────────────────────────────────────────────────────
// 每个请求发出前自动执行，把 JWT token 塞进请求头。
// 登录成功后 token 存在 localStorage，这里统一读取，
// 业务代码不需要每次手动写 Authorization header。
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// ── 响应拦截器 ──────────────────────────────────────────────────────────────
// 每个响应回来后自动执行。
// 正常响应（2xx）：直接透传，业务代码拿到的就是原始 response。
// 401 错误（token 过期或被吊销）：清掉本地 token 并跳转登录页，
//   加 pathname 判断是为了防止已在登录页时触发死循环跳转。
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("token");
      if (location.pathname !== "/login") location.href = "/login";
    }
    return Promise.reject(err); // 其他错误继续向上抛，由业务代码处理
  }
);

export default api;