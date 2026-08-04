# Multi-stage: the "ui-build" stage is the only place node/npm ever runs —
# never inside a running deployment (see docs/wiki/adr, "no node on the
# server" — the UI is compiled here, in CI, and baked into the final image
# as static files; a server never compiles anything).
FROM node:22-slim AS ui-build
WORKDIR /app/ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

# Same relative layout `prisma/server/web_app.py` already expects in dev
# mode (Path(__file__).parent.parent.parent / "ui" / "build") -- an
# editable install keeps that resolution working unchanged, whether the
# source came from a live git clone (dev mode) or is baked into an image
# (this Dockerfile).
COPY . .
COPY --from=ui-build /app/ui/build ./ui/build
RUN pip install --no-cache-dir -e .

EXPOSE 8765 8766 8767
CMD ["prisma", "serve", "--host", "0.0.0.0"]
