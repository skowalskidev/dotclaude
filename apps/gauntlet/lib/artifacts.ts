import path from "node:path";

const GENERATED_DIRECTORIES = new Set(["node_modules", "DerivedData", "SourcePackages"]);

export function isGeneratedArtifact(relativePath: string): boolean {
  return relativePath.split(path.sep).some((part) =>
    part.startsWith(".") || GENERATED_DIRECTORIES.has(part) || part.endsWith(".xcresult") ||
    part === "coverage" || /^coverage[-_][^.]+$/.test(part),
  );
}
