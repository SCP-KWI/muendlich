# muendlich — Chalk redesign (Observations)

Beautified frontend for the `muendlich` web app in the shared **Chalk** design
system, with the **Observations** accent (plum / Flieder), warm-neutral surfaces,
and a light/dark toggle. The redesign is almost entirely CSS — your React logic,
API layer, dictation hook, and data flow are untouched.

## Files to copy into `frontend/`

Copy these four over the same paths in your repo:

| File | Change |
|------|--------|
| `src/styles.css` | **Full rewrite** — Chalk tokens + every existing class restyled. Same class vocabulary, so no component depends on new markup. Light + dark via `html[data-theme="dark"]`. |
| `index.html` | Adds the Chalk fonts (Source Sans 3, IBM Plex Mono, Material Symbols) and a tiny pre-paint script that restores the saved theme. `theme-color` updated to plum. |
| `src/App.jsx` | Topbar now shows a brand mark + icons on the tabs, and a **light/dark toggle** button. Same state/handlers as before. |
| `src/Capture.jsx` | The mic button uses a Material Symbols icon instead of an emoji. Logic identical. |

Everything else (`DraftReview`, `Review`, `ClassOverview`, `StudentDetail`,
`Manage*`, `Login`, `ClassList`, `api.js`, `useDictation.js`) needs **no change** —
they already use the class names that `styles.css` styles.

## Preview

Open `preview.html` (it links the real `src/styles.css`) to see every screen in
both themes: Login, Capture, Class list, Draft review, Class overview,
Student detail, Manage, and the saved-confirmation. Use the toggle top-right.

## Notes

- **Sentiment colours:** positive = sage, neutral = neutral grey, negative = red —
  consistent across chips, trend bar, and observation borders.
- **Theme persistence:** stored in `localStorage` under `chalk-theme`; the inline
  script in `index.html` applies it before first paint so there's no flash.
- **PWA / offline:** the fonts load from Google Fonts' CDN. If you want them cached
  for full offline use, either add the two `fonts.googleapis`/`fonts.gstatic` URLs
  to your `vite-plugin-pwa` `runtimeCaching`, or self-host the font files. Online,
  they just work. (System fonts are the fallback until they load.)
- No new dependencies; no build-config changes.
