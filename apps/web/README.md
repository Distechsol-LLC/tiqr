# TiQR web

Not started. This folder will hold a SvelteKit app built to static files. It is not a separate
program: the API serves the build, so it ships inside the `tiqr` executable. The rules it
must follow, from [DEPLOYMENT.md](../../DEPLOYMENT.md):

- **Static build.** Use `@sveltejs/adapter-static` with `fallback: "index.html"`, so the backend
  serves one SPA shell for every non-API path. No Node.js runs on the customer's server.
- **Same origin, relative URLs.** Call the API as `fetch("/api/...")`, never an absolute URL or
  an IP. The browser already knows the server's address, so the build is identical for every
  customer and needs no CORS. In development, Vite's `server.proxy` forwards `/api` to a
  local `tiqr serve`.
- **Nothing private in the bundle.** Everything shipped to the browser is readable by anyone
  who loads the page. Minify, ship no source maps, and keep secrets, license checks and
  permission decisions on the server; the UI only hides what the API already forbids.
- **Build output.** `build/` is copied into the api package at release time and is
  git-ignored. Commit the package manager's lockfile and build with a locked install in CI.
