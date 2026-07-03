import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";
import { dirname } from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const eslintConfig = [...nextCoreWebVitals, ...nextTypescript, {
  rules: {
    // TypeScript rules
    "@typescript-eslint/no-explicit-any": "off",
    "@typescript-eslint/no-unused-vars": "off",
    "@typescript-eslint/no-non-null-assertion": "off",
    "@typescript-eslint/ban-ts-comment": "off",
    "@typescript-eslint/prefer-as-const": "off",
    "@typescript-eslint/no-unused-disable-directive": "off",
    
    // React rules
    "react-hooks/exhaustive-deps": "off",
    "react-hooks/purity": "off",
    // FIX: Disable react-hooks/set-state-in-effect — this React 19 rule flags
    // legitimate polling patterns (fetchData in useEffect that calls setState).
    // The dashboard's useApiData hook intentionally fetches on mount + interval;
    // refactoring to avoid the warning would harm readability without fixing a bug.
    "react-hooks/set-state-in-effect": "off",
    "react/no-unescaped-entities": "off",
    "react/display-name": "off",
    "react/prop-types": "off",
    "react-compiler/react-compiler": "off",
    
    // Next.js rules
    "@next/next/no-img-element": "off",
    "@next/next/no-html-link-for-pages": "off",
    
    // General JavaScript rules
    "prefer-const": "off",
    "no-unused-vars": "off",
    "no-console": "off",
    "no-debugger": "off",
    "no-empty": "off",
    "no-irregular-whitespace": "off",
    "no-case-declarations": "off",
    "no-fallthrough": "off",
    "no-mixed-spaces-and-tabs": "off",
    "no-redeclare": "off",
    "no-undef": "off",
    "no-unreachable": "off",
    "no-useless-escape": "off",
  },
}, {
  // FIX: Added .venv/**, .git/**, scripts/**, data/**, tests/**, *.py, *.db
  // to prevent eslint from scanning Python files (caused OOM/timeout in test report).
  ignores: [
    "node_modules/**",
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "examples/**",
    "skills/**",
    // Python venv & source (eslint should only lint src/)
    ".venv/**",
    "venv/**",
    ".git/**",
    "*.py",
    "*.db",
    "asi_engine/**",
    "config/**",
    "data_pipeline/**",
    "database/**",
    "engine/**",
    "executor/**",
    "jobs/**",
    "scrapers/**",
    "utils/**",
    "tests/**",
    "scripts/**",
    "data/**",
  ],
}];

export default eslintConfig;
