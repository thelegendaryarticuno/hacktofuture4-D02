import axios from "axios";

const api = axios.create({
  baseURL: "/api",
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const path = window.location.pathname || "/";
    const isPublicPath = path === "/" || path.startsWith("/autofix/report") || path.startsWith("/autofix/feedback");
    if (err.response?.status === 401 && !isPublicPath) {
      window.location.href = "/";
    }
    return Promise.reject(err);
  }
);

export default api;
