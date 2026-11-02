# PRPilot Brand Guide

Canonical domain: https://prpilot-one.vercel.app

Spelling rule: always write **PRPilot**, never "PR Pilot", never "PrPilot", never "prpilot" as a product name in prose. Repository and domain names keep their lowercase form (mirzasayzz/prpilot, prpilot-one.vercel.app) because those are identifiers, not the product name.

## Colours

| Token | Value | Use |
| --- | --- | --- |
| Background | #08080b | Page background, dark tile |
| Surface | #0f0f12 | Cards |
| Off-white ink | #f2efe6 | Headings and body text on dark |
| Secondary ink | #b0adb8 | Body supporting text |
| Muted ink | #a3a0ad | Labels and small supporting text. This replaces the old #726f7c, which scored 4.08:1 on #08080b and failed WCAG AA for normal text. #a3a0ad scores about 7.8:1 on #08080b. |
| Gold | #b8842f | Gradient start, secondary gold |
| Gold bright | #e3b862 | Accents, links, highlights |
| Success | #27a86f, bright #43d492 | Pass states. Renamed from the old finance token names. |
| Danger | #d94f4f, bright #f07a7a | Critical states. Renamed from the old finance token names. |
| Info | #7d8fd6 | Ambient accent only |

Do not reintroduce the old token names --bull, --bull-bright, --bear, or --bear-bright in new CSS. Existing code that still uses them should be migrated to --success and --danger.

## Fonts

- Display: Instrument Serif, for large headings.
- Sans: Inter, for body text and UI.
- Mono: JetBrains Mono, for labels, code, and small uppercase labels.

If a font fails to load, fall back in this order: serif to Georgia, sans to system-ui, mono to monospace. Never substitute a different display font for the wordmark lockup without updating logo-wordmark.svg as well.

## Logo variants and when to use each

All logo files live in public/. The mark is a PR branch glyph: a stem with two branches, round end nodes, and small sparkles. Keep the glyph intact. Do not redraw it, stretch it, recolour parts of it separately, or add a drop shadow.

- **public/logo.svg (existing):** Default dark tile with gold glyph. Use on the dark site, in the app, and anywhere the background is dark. This draft track did not change it, because the live read of that file was blocked (see NOTES.md). Check new variants against it before merging.
- **public/logo-light.svg:** Light tile (#f2efe6) with a dark branch glyph and gold accents. Use on light backgrounds, in documents, and in email where a dark tile would look like a hole.
- **public/logo-mono.svg:** Single-colour version, dark tile with white glyph. Use for single-colour printing, fax-like contexts, stamps, and anywhere only one ink is available. Recolour all parts together. Never add gold back into the mono version.
- **public/logo-wordmark.svg:** Branch mark plus the "PRPilot" wordmark in one lockup. Use in headers, slide title slides, and social headers where the name must appear with the mark. Do not typeset a separate wordmark next to the mark and call it the lockup.
- **public/logo.png (512 x 512):** Raster version of the dark mark, drawn with Python PIL for this draft (see MANIFEST.md). Use where a PNG is required and an SVG is not accepted.
- **public/apple-touch-icon.svg:** Simplified 180 x 180 mark, no text, full-bleed dark tile. Use for the Apple touch icon. Text is omitted on purpose: at icon size it would be unreadable.
- **public/og-image.png (1200 x 630) and public/og-image.svg:** Social preview. Use og-image.png for og:image and Twitter cards. Keep og-image.svg as the editable vector source. If the two drift, the PNG is the one that ships, so regenerate it from the SVG wording.

## Clearspace and minimum size

- Clearspace: leave at least the height of one branch end node clear on all sides of the mark. Do not place text, rules, or other logos inside that space.
- Minimum size: mark alone, 24 px on screen and 8 mm in print. Wordmark lockup, 120 px wide on screen and 30 mm in print. Social preview, always 1200 x 630, never cropped to a square.
- On a busy photo, place the mark on a solid dark tile. Never place the gold glyph directly on a busy image.

## Do-not rules

- Do not write "PR Pilot" or split the name.
- Do not claim "free forever", unlimited pull requests, or any compliance certification. The honest claims are: free to install, bring your own key, 25 reviews a day for non-owner installations by default.
- Do not invent install counts, testimonials, benchmarks, or review-time guarantees.
- Do not use the old domain prpilot-dun.vercel.app anywhere. The canonical domain is https://prpilot-one.vercel.app.
- Do not add a second gold, a gradient rainbow, or a new accent colour without updating this guide.
- Do not stretch, outline, or add effects to the glyph. Do not put the light logo on a dark background or the dark logo on a light background without checking contrast first.
- Do not use the mono logo in colour. That defeats its purpose.

## Honest claims checklist for any new page

Before publishing a page that uses this brand, check: no "free forever", no infinity symbol for pull requests, no compliance claim, the daily cap is stated for non-owners, the bring-your-own-key cost is stated, subprocessors are listed (Gemini, Groq, Cerebras, OpenRouter, LLMApi, Supabase, Vercel), and the canonical domain is prpilot-one.vercel.app.
