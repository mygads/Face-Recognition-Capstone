/** Pause background polling when the tab is hidden (hemat CPU/DB ala KAI).

Browser tetap menahan WebSocket/polling saat tab disembunyikan — puluhan guru
lupa menutup tab = puluhan snapshot DB tiap 2 dtk tanpa ada yang melihat.
Cek ringan ini dipakai sebelum setiap tick polling dan pada visibilitychange
untuk menutup WS dashboard lalu menyambung lagi saat tab terlihat.
*/
export function shouldPausePolling(): boolean {
  return typeof document !== 'undefined' && document.hidden === true
}
