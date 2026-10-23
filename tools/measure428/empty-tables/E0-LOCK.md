# #428 E0 dependency-lock receipt

The one approved lock-only run [39940235394](https://github.com/taipei49314/checkwash/actions/runs/39940235394), EC T-602, completed successfully on source `b6bb93d51a34addfc1c9eb81d03db458cfedf017`. It ran `npm install --package-lock-only --ignore-scripts --no-audit --no-fund`; no fixture or package script was executed.

- package-lock.json SHA256: `49775a1c24f4cf8546b7749a2fb6283f268818f4eff0f6a7dcf060fd392d64c7`
- Node: `v26.12.1`; npm: `11.20.0`
- ImageOS: `ubuntu24`; ImageVersion: `20261012.334.1`; architecture: `X64`
- Exact direct versions in the lock: Jest30.5.2, Vitest5.0.5, Vite8.3.5.
- Artifact: `issue428-resolve-lock-39940235394`, including the complete lock and setup-record files.

This commit only seals that returned lock for the later E1 packet. E1's30 fixture observations require a separately approved exact source and the above lock hash. No runner-equivalence result or #428 closure follows from E0 success. S1/S2 historical scope work remains separate.
