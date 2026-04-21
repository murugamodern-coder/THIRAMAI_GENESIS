import tokens from "./tokens.js";

export function getColor(mode, key) {
  if (mode === "dark") return tokens.colors.dark[key];
  if (mode === "light") return tokens.colors.light[key];
  return tokens.colors.brand[key] || tokens.colors.light[key];
}

export { tokens };
