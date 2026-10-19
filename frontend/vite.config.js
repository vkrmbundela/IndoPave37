import { createHash } from 'node:crypto'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Content-Security-Policy for the built site. GitHub Pages cannot send
// response headers, so the policy is a <meta> tag placed first in <head>
// (frame-ancestors and reporting are not available that way).
//  - Scripts: this origin, plus the inline theme script by its SHA-256 hash.
//  - The solver worker is same-origin; it loads Pyodide from jsDelivr under
//    its own worker policy, so the CDN does not need to be listed here.
//  - connect-src gains the API origin only when the build talks to a backend.
// The dev server is left alone (Vite injects inline scripts for HMR).
function contentSecurityPolicy(env) {
  return {
    name: 'indopave-csp',
    apply: 'build',
    transformIndexHtml: {
      order: 'post',
      handler(html) {
        const inline = [...html.matchAll(/<script\b(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)]
          .map((m) => `'sha256-${createHash('sha256').update(m[1], 'utf8').digest('base64')}'`)
        const connect = ["'self'"]
        if ((env.VITE_SOLVER_MODE || 'backend') !== 'browser') {
          try {
            connect.push(new URL(env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').origin)
          } catch {
            // A relative API path is on this origin, which 'self' already covers.
          }
        }
        const policy = [
          "default-src 'self'",
          `script-src 'self' ${inline.join(' ')}`.trim(),
          "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
          "font-src 'self' data: https://fonts.gstatic.com",
          "img-src 'self' data: blob:",
          `connect-src ${connect.join(' ')}`,
          "worker-src 'self'",
          "object-src 'none'",
          "base-uri 'self'",
          "form-action 'self'",
        ].join('; ')
        const tag = `<meta http-equiv="Content-Security-Policy" content="${policy}" />`
        return html.replace(/<meta charset[^>]*>/i, (m) => `${m}\n    ${tag}`)
      },
    },
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), 'VITE_'), ...process.env }
  return {
    base: process.env.VITE_BASE_PATH || '/',
    plugins: [
      react(),
      tailwindcss(),
      contentSecurityPolicy(env),
    ],
  }
})
