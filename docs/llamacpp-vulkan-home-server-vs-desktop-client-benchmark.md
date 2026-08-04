# llama.cpp + Vulkan: home server vs. desktop client, initial benchmark

Context: setting up a local llama.cpp (Vulkan backend) dev loop on both the
always-on home server (no dedicated GPU) and the daily-driver desktop client
workstation (also no dedicated GPU) so Prisma can eventually talk to either
Ollama or llama.cpp as interchangeable backends, tested locally on both
machines before anything ships to either box for real. Run 2026-07-23, while
the 4090M laptop (the machine all prior model-evaluation docs in this folder
used) is out for repair.

## Hardware

| | home server | desktop client |
|---|---|---|
| CPU | AMD Ryzen 7 PRO 6850U (8C/16T) | AMD Ryzen AI 5 PRO 340 (6C/12T, up to 4.9GHz) |
| GPU | Radeon 680M (RDNA2, "Rembrandt") | Radeon 840M (RDNA3.5, "Krackan1") |
| Matrix cores (Vulkan) | **none** | **`KHR_coopmat`** (cooperative matrix support) |
| RAM | 27GB, shared (UMA, no dedicated VRAM) | 22GB, shared (UMA, no dedicated VRAM) |
| Role | always-on server, models stay resident (`ttl: 0`) | interactive workstation, models load on-demand (`ttl`-based auto-unload) |

Both built from the same `ggml-org/llama.cpp` source (commit `c0bc8591e`),
`-DGGML_VULKAN=ON`, installed at `/opt/llama.cpp` (root-owned), RPATH patched
to `$ORIGIN` via `patchelf` for relocatability.

## Method

`llama-bench -m Qwen2.5-3B-Instruct-Q4_K_M.gguf -ngl 99`, full GPU offload,
default settings otherwise. Same model file (`bartowski/Qwen2.5-3B-Instruct-GGUF`,
Q4_K_M, 1.79GiB) on both machines.

## Results

| | home server (680M, no matrix cores) | desktop client (840M, `coopmat`) |
|---|---|---|
| pp512 (prompt processing, compute-bound) | **651.78 t/s** | 247.34 t/s |
| tg128 (generation, memory-bandwidth-bound) | 33.01 t/s | **35.88 t/s** |

## Analysis

Two results, in opposite directions from what "newer architecture + hardware
matrix acceleration" would suggest at first glance:

- **tg128 (decode)**: the desktop client slightly ahead (35.88 vs 33.01 t/s),
  consistent with decode being memory-bandwidth-bound rather than
  compute-bound — matrix cores don't help here regardless of generation,
  this is just whichever machine's RAM subsystem is faster.
- **pp512 (prefill)**: the desktop client is **2.6x slower** than the home
  server, despite having `coopmat` matrix-core support that the home
  server's 680M completely lacks (it reports `matrix cores: none` in
  `ggml_vulkan`'s device log). Not root-caused yet, but the leading
  hypothesis is **compute unit (CU) count**, not architecture generation:
  the home server's 680M (Rembrandt) is a relatively CU-generous config for
  its class; the 840M here is a lower/mid tier "Ryzen AI 5" part, and
  RDNA-generation improvements plus a `coopmat` efficiency win on paper
  don't necessarily overcome having meaningfully fewer raw shader/compute
  units to begin with. Not confirmed via an actual CU-count lookup for
  either chip — flagged as a follow-up if this matters enough to chase
  further.

## Takeaway for the Prisma dev-loop setup

Don't assume "newer chip generation" or "has matrix cores" predicts faster
inference — measure per-machine, per-workload (prefill vs decode behave
completely differently), same as every other model-choice finding in this
folder. The desktop client is not a strict upgrade over the home server for
this purpose: better for decode-heavy/short-generation workloads,
meaningfully worse for anything prompt-processing-heavy (e.g. feeding it
long context).
