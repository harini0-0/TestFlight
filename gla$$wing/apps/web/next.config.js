/** @type {import('next').NextConfig} */

// Next interpolates absolute paths with String.prototype.replace. In a
// replacement string, "$$" means a single "$", so a directory named
// gla$$wing is read back as gla$wing and the build cannot open its pages.
const originalReplace = String.prototype.replace;
const originalReplaceAll = String.prototype.replaceAll;

function preserveDollarPath(replacement) {
  if (typeof replacement === "string" && replacement.includes("$$") && replacement.startsWith("/")) {
    return () => replacement;
  }
  return replacement;
}

String.prototype.replace = function replace(pattern, replacement) {
  return originalReplace.call(this, pattern, preserveDollarPath(replacement));
};

String.prototype.replaceAll = function replaceAll(pattern, replacement) {
  return originalReplaceAll.call(this, pattern, preserveDollarPath(replacement));
};

const nextConfig = {
  reactStrictMode: true,
  outputFileTracingRoot: __dirname,
};

module.exports = nextConfig;
