// Phase 15 §4: "Tokens only -- no hard-coded colours/spacing (grep check in CI)." Scans every
// component/feature file for a literal hex or rgb()/rgba() colour outside the files that are
// legitimately allowed one: tokens.css itself (the source of truth), echartsTheme.ts (ECharts
// needs literal hex, it can't consume CSS custom properties) and this repo's own contrast script
// (reads tokens.css's literal values to check them).
//
//   npm run check:tokens
import { readFileSync } from "node:fs";
import { globSync } from "node:fs";
import { fileURLToPath } from "node:url";

const SRC = fileURLToPath(new URL("../src", import.meta.url));
const ALLOWED = [/styles[\\/]tokens\.css$/, /echartsTheme\.ts$/, /\.test\.ts$/];

const COLOR = /#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)/g;

const files = globSync(`${SRC}/**/*.{ts,tsx,css}`).filter(
  (f) => !ALLOWED.some((re) => re.test(f)),
);

let violations = 0;
for (const file of files) {
  const text = readFileSync(file, "utf8");
  const lines = text.split("\n");
  lines.forEach((line, i) => {
    const matches = line.match(COLOR);
    if (!matches) return;
    for (const m of matches) {
      // var(--accent-soft) etc. are fine -- it's the literal colour inside tokens.css that's
      // banned elsewhere, not referencing a token by name.
      if (/^rgba?\(\s*var\(/.test(m)) continue;
      console.log(`${file.replace(SRC, "src")}:${i + 1}  ${m}  -- ${line.trim()}`);
      violations++;
    }
  });
}

if (violations > 0) {
  console.error(`\n${violations} hard-coded colour(s) found -- use a token (tokens.css + tailwind.config.js) instead`);
  process.exit(1);
}
console.log("No hard-coded colours outside tokens.css / echartsTheme.ts");
