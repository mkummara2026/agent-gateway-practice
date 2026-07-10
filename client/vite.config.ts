import { defineConfig } from "vite";

// Proxies to the agentgateway Gateway. Requires:
//   kubectl port-forward -n agentgateway-system svc/agentgateway-proxy 8080:80
export default defineConfig({
  server: {
    proxy: {
      "/hr": "http://localhost:8080",
      "/payroll": "http://localhost:8080",
      "/it-support": "http://localhost:8080",
    },
  },
});
