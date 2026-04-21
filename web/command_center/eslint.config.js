import js from "@eslint/js";
import globals from "globals";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

const recommended = react.configs.flat.recommended;
const jsxRuntime = react.configs.flat["jsx-runtime"];

export default [
  {
    ignores: ["node_modules/**", "../../static/**", "dist/**", "bundle-stats.html"],
  },
  js.configs.recommended,
  {
    files: ["**/*.{js,jsx}"],
    plugins: {
      ...recommended.plugins,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    languageOptions: {
      ...recommended.languageOptions,
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        ...globals.browser,
      },
      parserOptions: {
        ...recommended.languageOptions.parserOptions,
        ...jsxRuntime.languageOptions.parserOptions,
        ecmaFeatures: { jsx: true },
      },
    },
    settings: {
      react: { version: "detect" },
    },
    rules: {
      ...recommended.rules,
      ...jsxRuntime.rules,
      "react/prop-types": "off",
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
      "no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
  {
    files: [
      "src/lib/hookDebug.js",
      "src/lib/telemetry.js",
      "src/lib/telemetryAlerts.js",
      "src/main.jsx",
      "src/components/ErrorBoundary.jsx",
    ],
    rules: {
      "no-console": "off",
    },
  },
  {
    files: ["src/lib/version.js"],
    languageOptions: {
      globals: {
        __CC_APP_VERSION__: "readonly",
        __CC_GIT_SHA__: "readonly",
      },
    },
  },
];
