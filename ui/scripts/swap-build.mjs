// Swaps the freshly-built "build-next" directory into "build" with two
// back-to-back renames instead of vite's rimraf-then-write, so
// prisma serve's web process (mounting "build" live via CleanUrlStaticFiles)
// never has a multi-second window where the directory is empty/partial and
// every request 404s.
import { existsSync, renameSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const uiDir = dirname(dirname(fileURLToPath(import.meta.url)));
const build = join(uiDir, "build");
const buildNext = join(uiDir, "build-next");
const buildOld = join(uiDir, "build-old");

if (!existsSync(buildNext)) {
  throw new Error(`swap-build: ${buildNext} does not exist — did the build step run?`);
}

if (existsSync(buildOld)) rmSync(buildOld, { recursive: true, force: true });
if (existsSync(build)) renameSync(build, buildOld);
renameSync(buildNext, build);
if (existsSync(buildOld)) rmSync(buildOld, { recursive: true, force: true });
