# Frontend shell

The internal dashboard remains Vue 3 + Vite + TypeScript. The web app uses Vue Router with separate `/auth` and `/app` layout branches; `/auth/login` is the authentication layout and `/app/dashboard` is the authenticated-area shell. This task establishes layout routing only; login/session enforcement and domain pages are separate work.

`gentelella@4.1.1` supplies the v4 SCSS design tokens (`gentelella/scss/v4/tokens`). The shell follows Gentelella's dark sidebar, compact topbar, teal accent, surfaces, spacing, and responsive drawer patterns. It does not import the full template runtime or its direct-DOM mutation scripts; Vue state owns the sidebar drawer, desktop rail, navigation, and theme control.

The color theme is stored as `presensi.theme` in local storage and falls back to the operating system preference. The sidebar currently contains only the implemented summary route. Add menu items alongside real screens as they are built.

The third-party MIT notice is in [gentelella-MIT.txt](../licenses/gentelella-MIT.txt); see [license notes](../licenses/README.md).
